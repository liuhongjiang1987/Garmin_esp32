# 模块级说明：单次/趋势分析队列。
# 单次：同步后入队 analyzing → Worker → succeeded；表盘点 ✓ 只读。
# 趋势：点选触发；成功报告按跨度缓存。无新数据再点同一跨度 → 直接读缓存，不跑模型。
# 新场次入队或该跨度指纹变化时才作废/重跑。

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.config import Settings, load_settings
from src.repository.swim_repo import SwimRepository
from src.session_analysis_agent import (
    TEMPLATE_ID as SESSION_TEMPLATE,
    run_session_analysis,
)
from src.trend_analysis_agent import (
    SPAN_DEFS,
    TEMPLATE_ID as TREND_TEMPLATE,
    load_trend_raw,
    run_trend_analysis,
)

_LOGGER = logging.getLogger("analysis_queue")

STATUS_IDLE = "idle"
STATUS_ANALYZING = "analyzing"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

# 表盘与自动入队只看最近 N 场，避免全历史拖死
RECENT_SESSION_LIMIT = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(repo: SwimRepository) -> sqlite3.Connection:
    conn = sqlite3.connect(repo._db_paths.coach_db)
    conn.row_factory = sqlite3.Row
    return conn


def _list_recent_session_summaries(
    repo: SwimRepository,
    *,
    limit: int = RECENT_SESSION_LIMIT,
) -> list[dict[str, Any]]:
    """轻量摘要：按时间新→旧。

    读本地 coach.db，不走 swim_evidence 网络盘（URI 全表扫可达 1s+，表盘会超时失败）。
    """
    from src.session_analysis_agent import pace_text

    with _connect(repo) as conn:
        rows = conn.execute("SELECT activity_id, evidence_json FROM activity_evidence").fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        evidence = json.loads(row["evidence_json"])
        level0 = evidence.get("l0") or {}
        level1 = evidence.get("l1") or {}
        pace = level1.get("avg_pace_per_100m_s")
        start_time = evidence.get("start_time")
        items.append(
            {
                "activity_id": str(row["activity_id"]),
                "start_time": start_time,
                "date": str(start_time)[:10] if start_time else "",
                "distance_m": level0.get("total_distance_m"),
                "swolf": level1.get("avg_swolf_derived"),
                "pace_text": pace_text(pace),
            }
        )
    items.sort(key=lambda x: str(x.get("start_time") or ""), reverse=True)
    return items[:limit]


def enqueue_session_jobs(
    repo: SwimRepository,
    *,
    limit: int = RECENT_SESSION_LIMIT,
) -> list[str]:
    """对最近 N 场中尚无成功报告的入队。"""
    newly: list[str] = []
    now = _now()
    recent = _list_recent_session_summaries(repo, limit=limit)
    with _connect(repo) as conn:
        existing = {
            row["activity_id"]: row["status"]
            for row in conn.execute("SELECT activity_id, status FROM session_analysis_jobs")
        }
        for item in recent:
            activity_id = item["activity_id"]
            prev = existing.get(activity_id)
            if prev in (STATUS_SUCCEEDED, STATUS_ANALYZING):
                continue
            conn.execute(
                """
                INSERT INTO session_analysis_jobs(activity_id, status, error, created_at, updated_at)
                VALUES (?, ?, NULL, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    status=excluded.status,
                    error=NULL,
                    updated_at=excluded.updated_at
                """,
                (activity_id, STATUS_ANALYZING, now, now),
            )
            newly.append(activity_id)
        # 清理误入队的超历史 analyzing，避免 Worker 扫几百场
        recent_ids = {item["activity_id"] for item in recent}
        if recent_ids:
            placeholders = ",".join("?" * len(recent_ids))
            conn.execute(
                f"""
                DELETE FROM session_analysis_jobs
                WHERE status = ? AND activity_id NOT IN ({placeholders})
                """,
                (STATUS_ANALYZING, *recent_ids),
            )
        conn.commit()
    if newly:
        _LOGGER.info("enqueued session jobs (%d): %s", len(newly), newly[:8])
    return newly


def trend_data_fingerprint(repo: SwimRepository, span: str) -> str:
    """窗口内场次指纹：无变化则可复用已存报告。"""
    raw = load_trend_raw(repo, span)
    sessions = raw.get("sessions") or []
    parts = [f"{s.get('activity_id')}:{s.get('start_time')}" for s in sessions]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{len(sessions)}:{digest}"


def invalidate_trend_cache(repo: SwimRepository) -> int:
    """作废已成功/失败的趋势缓存；进行中的任务保留。"""
    now = _now()
    with _connect(repo) as conn:
        spans = [
            row["span"]
            for row in conn.execute(
                "SELECT span FROM trend_analysis_jobs WHERE status IN (?, ?)",
                (STATUS_SUCCEEDED, STATUS_FAILED),
            )
        ]
        for span in spans:
            conn.execute("DELETE FROM trend_analysis_reports WHERE span = ?", (span,))
            conn.execute(
                """
                UPDATE trend_analysis_jobs
                SET status = ?, error = NULL, updated_at = ?
                WHERE span = ?
                """,
                (STATUS_IDLE, now, span),
            )
        conn.commit()
    if spans:
        _LOGGER.info("invalidated trend cache: %s", spans)
    return len(spans)


def _cached_trend_hit(repo: SwimRepository, span: str) -> bool:
    """有成功报告且指纹与当前窗口数据一致。"""
    with _connect(repo) as conn:
        row = conn.execute(
            """
            SELECT j.status, r.data_fingerprint
            FROM trend_analysis_jobs j
            JOIN trend_analysis_reports r ON r.span = j.span
            WHERE j.span = ?
            """,
            (span,),
        ).fetchone()
    if row is None or row["status"] != STATUS_SUCCEEDED:
        return False
    stored = row["data_fingerprint"]
    if not stored:
        # 旧报告无指纹：视为有效缓存，下次生成会写入指纹
        return True
    try:
        current = trend_data_fingerprint(repo, span)
    except Exception:
        _LOGGER.exception("fingerprint failed span=%s", span)
        return True
    if stored != current:
        _LOGGER.info("trend cache stale span=%s stored=%s current=%s", span, stored, current)
        return False
    return True


def request_trend_analysis(repo: SwimRepository, span: str) -> dict[str, Any]:
    """点选某跨度：缓存有效则直接可开（不调模型）；否则入队 analyzing。"""
    if span not in SPAN_DEFS:
        raise ValueError(f"未知跨度: {span}")
    label = SPAN_DEFS[span][0]
    now = _now()

    if _cached_trend_hit(repo, span):
        return {
            "span": span,
            "label": label,
            "status": STATUS_SUCCEEDED,
            "can_open": True,
            "started": False,
            "cached": True,
        }

    with _connect(repo) as conn:
        row = conn.execute(
            "SELECT status FROM trend_analysis_jobs WHERE span = ?",
            (span,),
        ).fetchone()
        status = row["status"] if row else STATUS_IDLE

        # 指纹过期：清掉旧报告，重新分析
        if status == STATUS_SUCCEEDED:
            conn.execute("DELETE FROM trend_analysis_reports WHERE span = ?", (span,))
            status = STATUS_IDLE

        if status != STATUS_ANALYZING:
            conn.execute(
                """
                INSERT INTO trend_analysis_jobs(span, status, error, created_at, updated_at)
                VALUES (?, ?, NULL, ?, ?)
                ON CONFLICT(span) DO UPDATE SET
                    status=excluded.status,
                    error=NULL,
                    updated_at=excluded.updated_at
                """,
                (span, STATUS_ANALYZING, now, now),
            )
            conn.commit()
            _LOGGER.info("requested trend analysis span=%s", span)
            return {
                "span": span,
                "label": label,
                "status": STATUS_ANALYZING,
                "can_open": False,
                "started": True,
                "cached": False,
            }

    return {
        "span": span,
        "label": label,
        "status": STATUS_ANALYZING,
        "can_open": False,
        "started": False,
        "cached": False,
    }


def get_trend_status(repo: SwimRepository, span: str) -> dict[str, Any]:
    """分析运行页轮询：status / can_open / label；含是否可走缓存。"""
    if span not in SPAN_DEFS:
        raise ValueError(f"未知跨度: {span}")
    label = SPAN_DEFS[span][0]
    cached = _cached_trend_hit(repo, span)
    with _connect(repo) as conn:
        row = conn.execute(
            "SELECT status, error FROM trend_analysis_jobs WHERE span = ?",
            (span,),
        ).fetchone()
    status = row["status"] if row else STATUS_IDLE
    if cached:
        status = STATUS_SUCCEEDED
    error = row["error"] if row else None
    return {
        "span": span,
        "label": label,
        "status": status,
        "can_open": status == STATUS_SUCCEEDED and cached,
        "cached": cached,
        "error": error,
    }


def process_session_jobs(
    repo: SwimRepository,
    settings: Settings | None = None,
    *,
    limit: int = 5,
) -> dict[str, int]:
    """处理排队中的单次分析；返回计数。"""
    settings = settings or load_settings()
    recent_ids = [item["activity_id"] for item in _list_recent_session_summaries(repo)]
    with _connect(repo) as conn:
        rows = conn.execute(
            """
            SELECT activity_id FROM session_analysis_jobs
            WHERE status = ?
            ORDER BY created_at
            """,
            (STATUS_ANALYZING,),
        ).fetchall()
    # 只处理最近窗口内的任务，且优先新场次
    pending = [row["activity_id"] for row in rows if row["activity_id"] in set(recent_ids)]
    pending.sort(key=lambda aid: recent_ids.index(aid) if aid in recent_ids else 999)
    ids = pending[:limit]
    ok = fail = 0
    for activity_id in ids:
        now = _now()
        try:
            report = run_session_analysis(repo, activity_id, settings=settings)
            with _connect(repo) as conn:
                conn.execute(
                    """
                    INSERT INTO session_analysis_reports(
                        activity_id, template_id, report_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(activity_id) DO UPDATE SET
                        template_id=excluded.template_id,
                        report_json=excluded.report_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        activity_id,
                        report.get("template_id") or SESSION_TEMPLATE,
                        json.dumps(report, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE session_analysis_jobs
                    SET status = ?, error = NULL, updated_at = ?
                    WHERE activity_id = ?
                    """,
                    (STATUS_SUCCEEDED, now, activity_id),
                )
                conn.commit()
            ok += 1
            _LOGGER.info("session job succeeded %s", activity_id)
        except Exception as exc:
            with _connect(repo) as conn:
                conn.execute(
                    """
                    UPDATE session_analysis_jobs
                    SET status = ?, error = ?, updated_at = ?
                    WHERE activity_id = ?
                    """,
                    (STATUS_FAILED, f"{type(exc).__name__}: {exc}"[:500], now, activity_id),
                )
                conn.commit()
            fail += 1
            _LOGGER.exception("session job failed %s", activity_id)
    return {"processed": len(ids), "succeeded": ok, "failed": fail}


def process_trend_jobs(
    repo: SwimRepository,
    settings: Settings | None = None,
    *,
    limit: int = 3,
    only_span: str | None = None,
) -> dict[str, int]:
    """处理排队中的趋势分析（仅用户点选入队的任务）。"""
    settings = settings or load_settings()
    with _connect(repo) as conn:
        if only_span:
            rows = conn.execute(
                """
                SELECT span FROM trend_analysis_jobs
                WHERE status = ? AND span = ?
                """,
                (STATUS_ANALYZING, only_span),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT span FROM trend_analysis_jobs
                WHERE status = ?
                ORDER BY created_at
                LIMIT ?
                """,
                (STATUS_ANALYZING, limit),
            ).fetchall()
    spans = [row["span"] for row in rows]
    ok = fail = 0
    for span in spans:
        now = _now()
        try:
            report = run_trend_analysis(repo, span, settings=settings)
            fingerprint = trend_data_fingerprint(repo, span)
            with _connect(repo) as conn:
                conn.execute(
                    """
                    INSERT INTO trend_analysis_reports(
                        span, template_id, report_json, data_fingerprint, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(span) DO UPDATE SET
                        template_id=excluded.template_id,
                        report_json=excluded.report_json,
                        data_fingerprint=excluded.data_fingerprint,
                        updated_at=excluded.updated_at
                    """,
                    (
                        span,
                        report.get("template_id") or TREND_TEMPLATE,
                        json.dumps(report, ensure_ascii=False),
                        fingerprint,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE trend_analysis_jobs
                    SET status = ?, error = NULL, updated_at = ?
                    WHERE span = ?
                    """,
                    (STATUS_SUCCEEDED, now, span),
                )
                conn.commit()
            ok += 1
            _LOGGER.info("trend job succeeded %s fingerprint=%s", span, fingerprint)
        except Exception as exc:
            with _connect(repo) as conn:
                conn.execute(
                    """
                    UPDATE trend_analysis_jobs
                    SET status = ?, error = ?, updated_at = ?
                    WHERE span = ?
                    """,
                    (STATUS_FAILED, f"{type(exc).__name__}: {exc}"[:500], now, span),
                )
                conn.commit()
            fail += 1
            _LOGGER.exception("trend job failed %s", span)
    return {"processed": len(spans), "succeeded": ok, "failed": fail}


def after_sync(
    repo: SwimRepository,
    settings: Settings | None = None,
    *,
    session_limit: int = 10,
    trend_limit: int = 3,
) -> dict[str, Any]:
    """同步后：入队单次；仅当有新场次时作废趋势缓存；消化已点选的趋势任务。"""
    settings = settings or load_settings()
    session_new = enqueue_session_jobs(repo)
    # 无新场次则保留各跨度已成功报告，下次点选直接读缓存
    invalidated = invalidate_trend_cache(repo) if session_new else 0
    session_stats = process_session_jobs(repo, settings, limit=session_limit)
    trend_stats = process_trend_jobs(repo, settings, limit=trend_limit)
    return {
        "session_enqueued": session_new,
        "trend_invalidated": invalidated,
        "session_process": session_stats,
        "trend_process": trend_stats,
    }


def list_sessions_for_ui(repo: SwimRepository, *, limit: int = 20) -> list[dict[str, Any]]:
    """表盘单次列表：摘要 + status（analyzing|succeeded|failed）。不调模型。"""
    # 入队只在 after_sync / Worker；列表只读，避免每次打开场次再扫一遍证据库（~1s+）
    summaries = _list_recent_session_summaries(repo, limit=limit)
    with _connect(repo) as conn:
        status_map = {
            row["activity_id"]: row["status"]
            for row in conn.execute("SELECT activity_id, status FROM session_analysis_jobs")
        }
    items: list[dict[str, Any]] = []
    for item in summaries:
        status = status_map.get(item["activity_id"], STATUS_ANALYZING)
        items.append(
            {
                **item,
                "status": status,
                "can_open": status == STATUS_SUCCEEDED,
            }
        )
    return items


def get_session_report(repo: SwimRepository, activity_id: str) -> dict[str, Any] | None:
    """只读已成功报告；无则 None。"""
    with _connect(repo) as conn:
        row = conn.execute(
            """
            SELECT r.report_json, j.status
            FROM session_analysis_reports r
            LEFT JOIN session_analysis_jobs j ON j.activity_id = r.activity_id
            WHERE r.activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
    if row is None:
        return None
    if row["status"] and row["status"] != STATUS_SUCCEEDED:
        return None
    from src.session_analysis_agent import sanitize_session_report

    # 旧报告可能含 2'14&quot;；读出时清洗，无需整库重跑
    return sanitize_session_report(json.loads(row["report_json"]))


def list_trends_for_ui(repo: SwimRepository) -> list[dict[str, Any]]:
    """九宫格：默认 idle；succeeded 且有报告则可直开（✓）；指纹过期在点选时重跑。"""
    with _connect(repo) as conn:
        rows = {
            row["span"]: dict(row)
            for row in conn.execute(
                """
                SELECT j.span, j.status, r.span AS has_report
                FROM trend_analysis_jobs j
                LEFT JOIN trend_analysis_reports r ON r.span = j.span
                """
            )
        }
    out = []
    for span, (label, _) in SPAN_DEFS.items():
        info = rows.get(span) or {}
        status = info.get("status") or STATUS_IDLE
        has_report = bool(info.get("has_report"))
        can_open = status == STATUS_SUCCEEDED and has_report
        out.append(
            {
                "span": span,
                "label": label,
                "status": status,
                "can_open": can_open,
                "cached": can_open,
            }
        )
    return out


def get_trend_report(repo: SwimRepository, span: str) -> dict[str, Any] | None:
    with _connect(repo) as conn:
        row = conn.execute(
            """
            SELECT r.report_json, j.status
            FROM trend_analysis_reports r
            LEFT JOIN trend_analysis_jobs j ON j.span = r.span
            WHERE r.span = ?
            """,
            (span,),
        ).fetchone()
    if row is None:
        return None
    if row["status"] and row["status"] != STATUS_SUCCEEDED:
        return None
    data = json.loads(row["report_json"])
    # 旧缓存字段名不齐时，按设计稿重写概览/进步/负荷（notes 保留）
    try:
        from src.trend_analysis_agent import apply_trend_design_pages, build_trend_datapack

        datapack = build_trend_datapack(repo, span)
        data = apply_trend_design_pages(data, datapack)
    except Exception:
        _LOGGER.exception("normalize trend report pages failed span=%s", span)
    return data
