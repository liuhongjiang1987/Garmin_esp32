# 模块级说明：单次分析 Agent（节目 A / session_bundle_v1）。
# 流程：装本场完整数据 → 代码算效率/耐力/稳定性指标 → Structured output 出报告。
# 不跑 SQL Agent，不继承对话 Skill。

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.config import Settings, load_settings
from src.repository.swim_repo import SwimRepository

_LOGGER = logging.getLogger("session_analysis")

TEMPLATE_ID = "session_bundle_v1"

# 分知识：约束说明文案，不参与选主题路由。
_DIMENSION_KNOWLEDGE = """
【效率】SWOLF=时间成本+动作成本，只与自己比；同池长同泳姿相近配速才有意义。
同速划次降或同划次配速升才是效率改善。配速变慢而 SWOLF 变好要警惕刷分（过长滑行）。
无划频划幅原始数据时不要编造。技术瑕疵用试探语气。

【耐力】看前半 vs 后半配速/SWOLF；后半同步变差多为疲劳漂移。
区分正常累与异常崩。不要编造乳酸/摄氧量。

【稳定性】看圈间配速波动与异常圈；忽快忽慢、泳姿乱切要指出。
禁止医疗诊断；疼/胸闷只建议休息与线下评估。

【下一步】只给一条可执行建议文案，不是跳转。可提「要课表去综合建议」。
配速一律使用数据包里已算好的文案（如 2'14"），不要重算或改成「分/秒」，禁止输出 HTML 实体（如 &quot;）。
全文必须简体中文：标题、label、notes、one_liner，禁止英文句子。
""".strip()


_STROKE_CN = {
    "freestyle": "自由泳",
    "backstroke": "仰泳",
    "breaststroke": "蛙泳",
    "butterfly": "蝶泳",
    "medley": "混合泳",
    "drill": "分解",
    "mixed": "混合",
    "im": "混合泳",
}


def _stroke_cn(hint: str) -> str:
    raw = str(hint or "").strip()
    if not raw:
        return ""
    key = raw.lower().replace(" ", "")
    return _STROKE_CN.get(key) or _STROKE_CN.get(raw.lower()) or raw


def _unescape_ui_text(text: str) -> str:
    """模型/工具常把 2'14\" 写成 2'14&quot;；墨水屏原样显示会乱。"""
    return (
        text.replace("&quot;", '"')
        .replace("&#34;", '"')
        .replace("&apos;", "'")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def _fmt_num(value: Any, *, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    if digits == 0:
        body = str(int(round(num)))
    else:
        body = f"{num:.{digits}f}".rstrip("0").rstrip(".")
    return f"{body}{suffix}"


def _rest_ratio_text(ratio: Any) -> str:
    if ratio is None:
        return "—"
    try:
        num = float(ratio)
    except (TypeError, ValueError):
        return "—"
    # 证据库多为 0~1；偶发已是百分数
    if 0 <= num <= 1.5:
        num *= 100
    text = f"{num:.1f}".rstrip("0").rstrip(".")
    return f"{text}%"


def sanitize_session_report(data: dict[str, Any]) -> dict[str, Any]:
    """清洗报告字符串：解码 HTML 实体，避免屏上出现 1'52&quot。"""

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return _unescape_ui_text(node)
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    return walk(data)


def apply_session_design_pages(data: dict[str, Any], datapack: dict[str, Any]) -> dict[str, Any]:
    """用代码指标覆盖各页 metrics/title；模型只保留 notes / one_liner。"""
    metrics = datapack.get("metrics") or {}
    display = metrics.get("session_display") or {}
    efficiency = metrics.get("efficiency") or {}
    endurance = metrics.get("endurance") or {}
    stability = metrics.get("stability") or {}

    by_id: dict[str, dict[str, Any]] = {}
    for page in data.get("pages") or []:
        if isinstance(page, dict) and page.get("page_id"):
            by_id[str(page["page_id"])] = page

    def keep_notes(page_id: str) -> list[str]:
        page = by_id.get(page_id) or {}
        notes = page.get("notes") or []
        return [_unescape_ui_text(str(n)) for n in notes if n][:2]

    dist = display.get("distance_m")
    try:
        dist_text = f"{int(round(float(dist)))}米" if dist is not None else "—"
    except (TypeError, ValueError):
        dist_text = "—"

    stroke_hints = [_stroke_cn(h) for h in (stability.get("stroke_hints") or []) if h]
    stroke_text = "/".join(stroke_hints[:3]) if stroke_hints else "—"
    outliers = stability.get("outlier_lap_indexes") or []
    outlier_text = ",".join(str(i) for i in outliers[:5]) if outliers else "—"

    overview = {
        "page_id": "overview",
        "title": "总览",
        "metrics": [
            {"label": "距离", "value": dist_text},
            {"label": "配速", "value": display.get("pace_text") or "—"},
            {"label": "SWOLF", "value": _fmt_num(display.get("swolf"), digits=0)},
            {"label": "休息比", "value": _rest_ratio_text(endurance.get("rest_ratio"))},
        ],
        "notes": keep_notes("overview"),
    }
    vs_base = "—"
    if efficiency.get("swolf_vs_baseline") is not None:
        try:
            vs_base = f"{float(efficiency['swolf_vs_baseline']):+.1f}"
        except (TypeError, ValueError):
            vs_base = "—"
    pace_drift = "—"
    if endurance.get("pace_drift_pct") is not None:
        try:
            pace_drift = f"{float(endurance['pace_drift_pct']):+.1f}%"
        except (TypeError, ValueError):
            pace_drift = "—"
    swolf_drift = "—"
    if endurance.get("swolf_drift") is not None:
        try:
            swolf_drift = f"{float(endurance['swolf_drift']):+.1f}"
        except (TypeError, ValueError):
            swolf_drift = "—"
    pace_cv = "—"
    if stability.get("pace_cv_pct") is not None:
        try:
            pace_cv = f"{float(stability['pace_cv_pct']):.1f}%"
        except (TypeError, ValueError):
            pace_cv = "—"

    efficiency_page = {
        "page_id": "efficiency",
        "title": "效率",
        "metrics": [
            {"label": "SWOLF", "value": _fmt_num(efficiency.get("avg_swolf"), digits=0)},
            {"label": "vs基线", "value": vs_base},
            {"label": "前半", "value": _fmt_num(efficiency.get("first_half_swolf"), digits=1)},
            {"label": "后半", "value": _fmt_num(efficiency.get("second_half_swolf"), digits=1)},
        ],
        "notes": keep_notes("efficiency"),
    }
    endurance_page = {
        "page_id": "endurance",
        "title": "耐力",
        "metrics": [
            {"label": "前半配速", "value": endurance.get("first_half_pace_text") or "—"},
            {"label": "后半配速", "value": endurance.get("second_half_pace_text") or "—"},
            {"label": "配速漂移", "value": pace_drift},
            {"label": "SWOLF漂移", "value": swolf_drift},
        ],
        "notes": keep_notes("endurance"),
    }
    stability_page = {
        "page_id": "stability",
        "title": "稳定",
        "metrics": [
            {"label": "配速波动", "value": pace_cv},
            {"label": "异常圈", "value": outlier_text},
            {"label": "泳姿", "value": stroke_text[:16]},
            {"label": "泳姿种数", "value": _fmt_num(stability.get("stroke_hint_count"), digits=0)},
        ],
        "notes": keep_notes("stability"),
    }

    next_step = by_id.get("next_step") or {
        "page_id": "next_step",
        "title": "下一步",
        "metrics": [],
        "notes": [],
    }
    next_step = {
        "page_id": "next_step",
        "title": "下一步",
        "metrics": [],
        "notes": [_unescape_ui_text(str(n)) for n in (next_step.get("notes") or []) if n][:2],
    }

    headline = data.get("headline") if isinstance(data.get("headline"), dict) else {}
    if isinstance(headline.get("one_liner"), str):
        headline["one_liner"] = _unescape_ui_text(headline["one_liner"])

    return {**data, "headline": headline, "pages": [overview, efficiency_page, endurance_page, stability_page, next_step]}


# =============================================================================
# 报告 Schema（Structured output）
# =============================================================================


class ReportMetric(BaseModel):
    """小屏一行指标。"""

    label: str = Field(description="指标名，最多10字", max_length=10)
    value: str = Field(description="已格式化的值，最多16字", max_length=16)


class ReportPage(BaseModel):
    """报告一页。"""

    page_id: Literal["overview", "efficiency", "endurance", "stability", "next_step"]
    title: str = Field(max_length=12)
    metrics: list[ReportMetric] = Field(default_factory=list, max_length=4)
    notes: list[str] = Field(default_factory=list, max_length=2, description="每条最多64字")


class SessionHeadline(BaseModel):
    """本场速览。"""

    one_liner: str = Field(description="一句总评，竖屏两行内", max_length=48)
    distance_m: float | None = None
    pace_text: str | None = None
    swolf: float | None = None


class SessionAnalysisReport(BaseModel):
    """单次游泳分析报告，供 200×200 墨水屏分页。"""

    activity_id: str
    template_id: str = TEMPLATE_ID
    headline: SessionHeadline
    pages: list[ReportPage] = Field(min_length=1)


# =============================================================================
# 工具函数与装包
# =============================================================================


def pace_text(seconds: Any) -> str | None:
    """秒/100米 → 设计稿配速文案，如 2'14\"。"""
    if seconds is None:
        return None
    total = int(round(float(seconds)))
    return f"{total // 60}'{total % 60:02d}\""


def _evidence_db_path(repo: SwimRepository) -> Path:
    settings = load_settings()
    return settings.swim_evidence_db_path or repo._db_paths.coach_db


def open_evidence_db(repo: SwimRepository) -> sqlite3.Connection:
    """只读打开 swim_evidence（或回退 coach.db）。"""
    path = _evidence_db_path(repo)
    # 逐行注释：证据库用 URI 只读；活动库 ATTACH 失败时仍可继续（start_time 可从 evidence JSON 取）。
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    activities_db = repo._db_paths.garmin_activities_db
    if activities_db.is_file():
        try:
            conn.execute("ATTACH DATABASE ? AS act", (str(activities_db),))
        except sqlite3.Error:
            pass
    return conn


def load_session_raw(repo: SwimRepository, activity_id: str) -> dict[str, Any]:
    """装本场完整切片：session + 全部 laps + 档案（不含 LLM）。"""
    conn = open_evidence_db(repo)
    try:
        ev_row = conn.execute(
            "SELECT evidence_json FROM activity_evidence WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        if ev_row is None:
            raise ValueError(f"找不到活动证据: {activity_id}")
        evidence = json.loads(ev_row["evidence_json"])
        level0 = evidence.get("l0") or {}
        level1 = evidence.get("l1") or {}
        start_time = evidence.get("start_time")
        if start_time is None:
            row = conn.execute(
                "SELECT start_time FROM act.activities WHERE activity_id = ?",
                (activity_id,),
            ).fetchone()
            start_time = row["start_time"] if row else None
        pace = level1.get("avg_pace_per_100m_s")
        session = {
            "activity_id": activity_id,
            "start_time": start_time,
            "distance_m": level0.get("total_distance_m"),
            "avg_pace_s": pace,
            "avg_pace_text": pace_text(pace),
            "avg_swolf": level1.get("avg_swolf_derived"),
            "avg_hr": level0.get("avg_hr"),
            "max_hr": level0.get("max_hr"),
            "total_strokes": level0.get("total_strokes"),
            "rest_time_s": level1.get("rest_time_s"),
            "rest_ratio": level1.get("rest_time_ratio"),
        }
        lap_rows = conn.execute(
            """
            SELECT activity_id, lap_index, distance_m, elapsed_s, pace_per_100m_s,
                   avg_hr, max_hr, total_strokes, swim_stroke_hint, swolf_derived, is_rest_lap
            FROM swim_laps_enriched
            WHERE activity_id = ?
            ORDER BY lap_index
            """,
            (activity_id,),
        ).fetchall()
        laps = [
            {
                "lap_index": row["lap_index"],
                "distance_m": row["distance_m"],
                "elapsed_s": row["elapsed_s"],
                "pace_per_100m_s": row["pace_per_100m_s"],
                "pace_text": pace_text(row["pace_per_100m_s"]),
                "avg_hr": row["avg_hr"],
                "max_hr": row["max_hr"],
                "total_strokes": row["total_strokes"],
                "swim_stroke_hint": row["swim_stroke_hint"],
                "swolf_derived": row["swolf_derived"],
                "is_rest_lap": int(row["is_rest_lap"] or 0),
            }
            for row in lap_rows
        ]
    finally:
        conn.close()

    profile = repo.get_profile("default") or {}
    baseline = _compute_baseline(repo, activity_id, session.get("start_time"))
    return {
        "template_id": TEMPLATE_ID,
        "profile": {
            "pool_length_m": profile.get("pool_length_m"),
            "goal": profile.get("goal"),
            "sex": profile.get("sex"),
            "age": profile.get("age"),
        },
        "session": session,
        "laps": laps,
        "baseline": baseline,
    }


def _compute_baseline(
    repo: SwimRepository,
    activity_id: str,
    start_time: str | None,
) -> dict[str, Any]:
    """近若干场同运动员均值；不足 3 场则关键数字为 null。"""
    conn = open_evidence_db(repo)
    try:
        rows = conn.execute("SELECT activity_id, evidence_json FROM activity_evidence").fetchall()
    finally:
        conn.close()
    peers: list[dict[str, Any]] = []
    for row in rows:
        if row["activity_id"] == activity_id:
            continue
        evidence = json.loads(row["evidence_json"])
        st = str(evidence.get("start_time") or "")
        if start_time and st > str(start_time):
            continue
        level1 = evidence.get("l1") or {}
        peers.append(
            {
                "start_time": st,
                "pace": level1.get("avg_pace_per_100m_s"),
                "swolf": level1.get("avg_swolf_derived"),
            }
        )
    peers.sort(key=lambda x: x["start_time"], reverse=True)
    peers = peers[:8]
    paces = [p["pace"] for p in peers if p["pace"] is not None]
    swolfs = [p["swolf"] for p in peers if p["swolf"] is not None]
    enough = len(paces) >= 3 and len(swolfs) >= 3
    return {
        "sample_count": len(peers),
        "recent_avg_pace_s": (sum(paces) / len(paces)) if enough else None,
        "recent_avg_swolf": (sum(swolfs) / len(swolfs)) if enough else None,
        "note": "近场次均值；不足3场关键数字为null",
    }


def compute_session_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    """代码侧算死三维指标，供模型填 notes，禁止模型重算。"""
    session = raw["session"]
    laps = [lap for lap in raw["laps"] if not lap.get("is_rest_lap")]
    baseline = raw.get("baseline") or {}

    paces = [float(lap["pace_per_100m_s"]) for lap in laps if lap.get("pace_per_100m_s") is not None]
    swolfs = [float(lap["swolf_derived"]) for lap in laps if lap.get("swolf_derived") is not None]
    mid = max(len(paces) // 2, 1)
    first_paces, second_paces = paces[:mid], paces[mid:] or paces[-1:]
    first_swolf, second_swolf = swolfs[:mid], swolfs[mid:] or swolfs[-1:]

    def _avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    first_pace_avg = _avg(first_paces)
    second_pace_avg = _avg(second_paces)
    first_swolf_avg = _avg(first_swolf)
    second_swolf_avg = _avg(second_swolf)
    pace_drift_pct = None
    if first_pace_avg and second_pace_avg and first_pace_avg > 0:
        pace_drift_pct = round((second_pace_avg - first_pace_avg) / first_pace_avg * 100, 1)
    swolf_drift = None
    if first_swolf_avg is not None and second_swolf_avg is not None:
        swolf_drift = round(second_swolf_avg - first_swolf_avg, 1)

    pace_cv = None
    if len(paces) >= 2:
        mean = statistics.mean(paces)
        if mean > 0:
            pace_cv = round(statistics.pstdev(paces) / mean * 100, 1)

    outliers: list[int] = []
    if len(paces) >= 3:
        mean = statistics.mean(paces)
        stdev = statistics.pstdev(paces)
        if stdev > 0:
            for lap, pace in zip(laps, paces):
                if abs(pace - mean) >= 1.5 * stdev:
                    outliers.append(int(lap["lap_index"]))

    strokes = [lap for lap in raw["laps"]]
    stroke_hints = {str(lap.get("swim_stroke_hint") or "") for lap in strokes if lap.get("swim_stroke_hint")}
    stroke_hints.discard("")

    avg_swolf = session.get("avg_swolf")
    base_swolf = baseline.get("recent_avg_swolf")
    swolf_vs_base = None
    if avg_swolf is not None and base_swolf is not None:
        swolf_vs_base = round(float(avg_swolf) - float(base_swolf), 1)

    avg_pace = session.get("avg_pace_s")
    base_pace = baseline.get("recent_avg_pace_s")
    # 刷分嫌疑：比基线配速更慢（秒数更大）且 SWOLF 更好（更小）
    sandbag_suspect = False
    if (
        avg_pace is not None
        and base_pace is not None
        and avg_swolf is not None
        and base_swolf is not None
        and float(avg_pace) > float(base_pace) * 1.03
        and float(avg_swolf) < float(base_swolf) - 1
    ):
        sandbag_suspect = True

    return {
        "efficiency": {
            "avg_swolf": avg_swolf,
            "swolf_vs_baseline": swolf_vs_base,
            "first_half_swolf": round(first_swolf_avg, 1) if first_swolf_avg is not None else None,
            "second_half_swolf": round(second_swolf_avg, 1) if second_swolf_avg is not None else None,
            "total_strokes": session.get("total_strokes"),
            "sandbag_suspect": sandbag_suspect,
            "baseline_ready": baseline.get("recent_avg_swolf") is not None,
        },
        "endurance": {
            "first_half_pace_text": pace_text(first_pace_avg),
            "second_half_pace_text": pace_text(second_pace_avg),
            "pace_drift_pct": pace_drift_pct,
            "swolf_drift": swolf_drift,
            "rest_ratio": session.get("rest_ratio"),
            "active_lap_count": len(laps),
        },
        "stability": {
            "pace_cv_pct": pace_cv,
            "outlier_lap_indexes": outliers[:5],
            "stroke_hint_count": len(stroke_hints),
            "stroke_hints": sorted(stroke_hints)[:4],
        },
        "session_display": {
            "distance_m": session.get("distance_m"),
            "pace_text": session.get("avg_pace_text"),
            "swolf": avg_swolf,
            "start_time": session.get("start_time"),
        },
    }


def build_session_datapack(repo: SwimRepository, activity_id: str) -> dict[str, Any]:
    """完整装包：原始切片 + 已算 metrics。"""
    raw = load_session_raw(repo, activity_id)
    metrics = compute_session_metrics(raw)
    return {**raw, "metrics": metrics}


# =============================================================================
# Agent
# =============================================================================


def _chat_model(settings: Settings) -> ChatOpenAI:
    if not settings.model_api_key or not settings.model_base_url:
        raise RuntimeError("缺少 SILICONFLOW_API_KEY 或 SILICONFLOW_BASE_URL")
    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        temperature=0.2,
    )


def create_session_analysis_agent(settings: Settings | None = None):
    """创建单次分析 Agent（仅 Structured output，无工具）。"""
    settings = settings or load_settings()
    model = _chat_model(settings)
    return create_agent(
        model=model,
        tools=[],
        system_prompt=(
            "你是游泳单次分析写手。输入已含完整本场数据与代码算好的 metrics。"
            "只根据 metrics 与分知识填写 SessionAnalysisReport："
            "headline.one_liner + pages（overview/efficiency/endurance/stability/next_step）。"
            "页 metrics 的数字服务端会用代码覆盖；你重点写 notes 与 one_liner。"
            "notes 每页最多2句，每句简短适配墨水屏；必须简体中文，禁止英文句与 HTML 实体。"
            f"\n\n{_DIMENSION_KNOWLEDGE}"
        ),
        response_format=ToolStrategy(SessionAnalysisReport),
    )


def run_session_analysis(
    repo: SwimRepository,
    activity_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """装包 → 调用 Agent → 返回报告 dict（含 activity_id / template_id）。"""
    settings = settings or load_settings()
    datapack = build_session_datapack(repo, activity_id)
    agent = create_session_analysis_agent(settings)
    user_payload = json.dumps(datapack, ensure_ascii=False, default=str)
    _LOGGER.info("session analysis start activity_id=%s laps=%s", activity_id, len(datapack.get("laps") or []))
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"请为 activity_id={activity_id} 生成单次分析报告。"
                        f"template_id 必须是 {TEMPLATE_ID}。\n"
                        f"数据包如下：\n{user_payload}"
                    ),
                }
            ]
        }
    )
    report = result.get("structured_response")
    if report is None:
        raise RuntimeError("单次分析未返回 structured_response")
    if isinstance(report, BaseModel):
        data = report.model_dump()
    else:
        data = dict(report)
    data["activity_id"] = activity_id
    data["template_id"] = TEMPLATE_ID
    # 用代码侧数字覆盖 headline / 各页 metrics，避免模型改数或写成 &quot;
    display = datapack["metrics"]["session_display"]
    headline = data.setdefault("headline", {})
    if isinstance(headline, dict):
        headline["distance_m"] = display.get("distance_m")
        headline["pace_text"] = display.get("pace_text")
        headline["swolf"] = display.get("swolf")
    data = apply_session_design_pages(data, datapack)
    data = sanitize_session_report(data)
    _LOGGER.info("session analysis done activity_id=%s pages=%s", activity_id, len(data.get("pages") or []))
    return data


def report_to_json(report: dict[str, Any]) -> str:
    """序列化报告。"""
    return json.dumps(report, ensure_ascii=False, indent=2)
