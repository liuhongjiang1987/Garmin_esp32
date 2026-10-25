# 模块级说明：趋势分析 Agent（节目 B / trend_bundle_v1）。
# 流程：按时间跨度装多场汇总 → 代码算进步/负荷指标与 charts 点列 → Structured output 出文案。
# 落库前把配速/SWOLF/距离序列合并进报告，供前端画简易折线图；模型只写 chart_notes。
# 场次 <3 仍出报告，总评标明样本不足。不跑 SQL Agent，不继承对话 Skill。

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.config import Settings, load_settings
from src.repository.swim_repo import SwimRepository

_LOGGER = logging.getLogger("trend_analysis")

TEMPLATE_ID = "trend_bundle_v1"
# 墨水屏折线图点数上限（设计稿 SWOLF 趋势约 6 点）
CHART_MAX_POINTS = 6

# 跨度 key → 显示文案与天数（月/年用近似天数，装包时按日历裁切）
SPAN_DEFS: dict[str, tuple[str, int]] = {
    "1w": ("1周", 7),
    "2w": ("2周", 14),
    "3w": ("3周", 21),
    "1m": ("1个月", 31),
    "2m": ("2个月", 62),
    "3m": ("3个月", 93),
    "6m": ("6个月", 186),
    "9m": ("9个月", 279),
    "1y": ("1年", 366),
}

_DIMENSION_KNOWLEDGE = """
【进步】看窗口内配速/SWOLF/距离随时间的方向：进步、平台、回落、伪进步。
伪进步=单次最好变好但整体一致性变差。样本不足（场次<3）时只描述样本，不下强结论。

【负荷】用场次密度与总距离等本地可算代理判断刺激是否偏猛；无官方 Training Load 不要假装有。
风险用低/中/高知识口径，禁止医疗诊断。

【折线图说明】metrics.charts 里已有配速/SWOLF/距离序列（代码算死）。
你只写 chart_notes 各一条短说明（适配墨水屏，一句即可），例如「近6次整体下降，效率在变好」。
不要改写 charts 里的数字。SWOLF 下降通常表示效率变好。

【下一步】一条周期向建议文案，不是跳转。配速用已算好的分秒文案。
""".strip()


# =============================================================================
# 报告 Schema
# =============================================================================


class ReportMetric(BaseModel):
    label: str = Field(max_length=10)
    value: str = Field(max_length=16)


class ReportPage(BaseModel):
    page_id: Literal["overview", "progress", "load", "next_step"]
    title: str = Field(max_length=12)
    metrics: list[ReportMetric] = Field(default_factory=list, max_length=4)
    notes: list[str] = Field(default_factory=list, max_length=2)


class TrendHeadline(BaseModel):
    one_liner: str = Field(max_length=48, description="一句总评；样本不足时必须点明")
    span_label: str | None = None
    session_count: int | None = None
    total_distance_m: float | None = None
    sample_insufficient: bool = False


class ChartNotes(BaseModel):
    """三张折线图各自一句说明（数字序列由代码注入，不在此输出）。"""

    swolf: str = Field(max_length=64, description="SWOLF 折线说明")
    pace: str = Field(max_length=64, description="配速折线说明")
    distance: str = Field(max_length=64, description="距离折线说明")


class TrendAnalysisReport(BaseModel):
    """趋势分析报告：文案页 + 折线说明；配速/SWOLF/距离点列由服务端合并进 charts。"""

    span: str
    template_id: str = TEMPLATE_ID
    headline: TrendHeadline
    pages: list[ReportPage] = Field(min_length=1)
    chart_notes: ChartNotes


# =============================================================================
# 装包与指标
# =============================================================================


def pace_text(seconds: Any) -> str | None:
    if seconds is None:
        return None
    total = int(round(float(seconds)))
    return f"{total // 60}分{total % 60:02d}秒/100米"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            if fmt is None:
                return datetime.fromisoformat(text)
            return datetime.strptime(str(value)[:19], fmt)
        except ValueError:
            continue
    return None


def _evidence_db_path(repo: SwimRepository) -> Path:
    settings = load_settings()
    return settings.swim_evidence_db_path or repo._db_paths.coach_db


def _list_session_summaries(repo: SwimRepository) -> list[dict[str, Any]]:
    path = _evidence_db_path(repo)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        activities_db = repo._db_paths.garmin_activities_db
        starts: dict[str, str] = {}
        if activities_db.is_file():
            conn.execute("ATTACH DATABASE ? AS act", (f"file:{activities_db}?mode=ro",))
            starts = {
                row["activity_id"]: row["start_time"]
                for row in conn.execute(
                    "SELECT activity_id, start_time FROM act.activities WHERE sport = 'swimming'"
                )
            }
        rows = conn.execute("SELECT activity_id, evidence_json FROM activity_evidence").fetchall()
    finally:
        conn.close()

    sessions: list[dict[str, Any]] = []
    for row in rows:
        evidence = json.loads(row["evidence_json"])
        level0 = evidence.get("l0") or {}
        level1 = evidence.get("l1") or {}
        start_time = evidence.get("start_time") or starts.get(row["activity_id"])
        pace = level1.get("avg_pace_per_100m_s")
        sessions.append(
            {
                "activity_id": row["activity_id"],
                "start_time": start_time,
                "distance_m": level0.get("total_distance_m"),
                "avg_pace_s": pace,
                "avg_pace_text": pace_text(pace),
                "avg_swolf": level1.get("avg_swolf_derived"),
                "avg_hr": level0.get("avg_hr"),
                "rest_ratio": level1.get("rest_time_ratio"),
            }
        )
    sessions.sort(key=lambda s: str(s.get("start_time") or ""))
    return sessions


def load_trend_raw(
    repo: SwimRepository,
    span: str,
    *,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    """按跨度装多场汇总 + 档案。不含圈明细。"""
    if span not in SPAN_DEFS:
        raise ValueError(f"未知跨度: {span}，可选 {list(SPAN_DEFS)}")
    label, days = SPAN_DEFS[span]
    end = end_time or datetime.now()
    start = end - timedelta(days=days)
    all_sessions = _list_session_summaries(repo)
    window: list[dict[str, Any]] = []
    for item in all_sessions:
        ts = _parse_time(item.get("start_time"))
        if ts is None:
            continue
        # 去掉时区再比
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        if start <= ts <= end:
            window.append(item)

    profile = repo.get_profile("default") or {}
    return {
        "template_id": TEMPLATE_ID,
        "span": span,
        "span_label": label,
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "profile": {
            "pool_length_m": profile.get("pool_length_m"),
            "goal": profile.get("goal"),
            "sex": profile.get("sex"),
            "age": profile.get("age"),
        },
        "sessions": window,
    }


def _slope(xs: list[float], ys: list[float]) -> float | None:
    """简单线性斜率 dy/dx；点不足返回 null。"""
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom <= 0:
        return None
    numer = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return numer / denom


def build_chart_series(sessions: list[dict[str, Any]], *, max_points: int = CHART_MAX_POINTS) -> dict[str, Any]:
    """供前端画简易折线：配速 / SWOLF / 距离。按时间升序，最多 max_points 个点（取窗口末段）。"""
    ordered = sorted(sessions, key=lambda s: str(s.get("start_time") or ""))
    if len(ordered) > max_points:
        ordered = ordered[-max_points:]

    swolf_pts: list[dict[str, Any]] = []
    pace_pts: list[dict[str, Any]] = []
    distance_pts: list[dict[str, Any]] = []
    for i, item in enumerate(ordered, start=1):
        start = item.get("start_time")
        date = str(start)[:10] if start else ""
        base = {
            "index": i,
            "activity_id": item.get("activity_id"),
            "date": date,
            "start_time": start,
        }
        if item.get("avg_swolf") is not None:
            swolf_pts.append({**base, "value": round(float(item["avg_swolf"]), 1)})
        if item.get("avg_pace_s") is not None:
            pace_s = float(item["avg_pace_s"])
            pace_pts.append(
                {
                    **base,
                    "value": round(pace_s, 1),
                    "value_text": item.get("avg_pace_text") or pace_text(pace_s),
                }
            )
        if item.get("distance_m") is not None:
            distance_pts.append({**base, "value": round(float(item["distance_m"]), 1)})

    return {
        "swolf": {
            "key": "swolf",
            "title": "SWOLF趋势分析",
            "unit": "",
            "lower_is_better": True,
            "points": swolf_pts,
        },
        "pace": {
            "key": "pace",
            "title": "配速趋势分析",
            "unit": "s/100m",
            "lower_is_better": True,
            "points": pace_pts,
        },
        "distance": {
            "key": "distance",
            "title": "距离趋势分析",
            "unit": "m",
            "lower_is_better": False,
            "points": distance_pts,
        },
    }


def compute_trend_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    """代码侧算进步与负荷代理指标，并附带折线序列。"""
    sessions = raw.get("sessions") or []
    count = len(sessions)
    sample_insufficient = count < 3
    distances = [float(s["distance_m"]) for s in sessions if s.get("distance_m") is not None]
    total_distance = sum(distances) if distances else 0.0

    timed: list[tuple[float, float, float]] = []
    for item in sessions:
        ts = _parse_time(item.get("start_time"))
        if ts is None:
            continue
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        day = ts.timestamp() / 86400.0
        pace = item.get("avg_pace_s")
        swolf = item.get("avg_swolf")
        if pace is not None and swolf is not None:
            timed.append((day, float(pace), float(swolf)))

    days = [t[0] for t in timed]
    paces = [t[1] for t in timed]
    swolfs = [t[2] for t in timed]
    # 斜率：每天变化；再乘 7 得到「每周」
    pace_slope_per_day = _slope(days, paces)
    swolf_slope_per_day = _slope(days, swolfs)
    pace_slope_week = round(pace_slope_per_day * 7, 2) if pace_slope_per_day is not None else None
    swolf_slope_week = round(swolf_slope_per_day * 7, 2) if swolf_slope_per_day is not None else None

    avg_pace = sum(paces) / len(paces) if paces else None
    avg_swolf = sum(swolfs) / len(swolfs) if swolfs else None

    # 负荷代理：周均场次、周均距离（按窗口天数折算）
    _, span_days = SPAN_DEFS[raw["span"]]
    weeks = max(span_days / 7.0, 1.0)
    sessions_per_week = round(count / weeks, 2)
    distance_per_week = round(total_distance / weeks, 1)

    # 粗风险：场次密度高且总距大 → 偏高（知识版，非医疗）
    risk = "低"
    if not sample_insufficient:
        if sessions_per_week >= 5 or distance_per_week >= 8000:
            risk = "高"
        elif sessions_per_week >= 3.5 or distance_per_week >= 5000:
            risk = "中"

    charts = build_chart_series(sessions)

    return {
        "sample_insufficient": sample_insufficient,
        "session_count": count,
        "total_distance_m": total_distance,
        "progress": {
            "avg_pace_s": avg_pace,
            "avg_pace_text": pace_text(avg_pace),
            "avg_swolf": round(avg_swolf, 1) if avg_swolf is not None else None,
            "pace_slope_s_per_week": pace_slope_week,
            "swolf_slope_per_week": swolf_slope_week,
            # 配速斜率>0 表示变慢；SWOLF 斜率>0 表示效率变差
            "pace_getting_slower": (pace_slope_week is not None and pace_slope_week > 0.5),
            "swolf_getting_worse": (swolf_slope_week is not None and swolf_slope_week > 0.3),
        },
        "load": {
            "sessions_per_week": sessions_per_week,
            "distance_m_per_week": distance_per_week,
            "risk_level": risk,
        },
        "display": {
            "span_label": raw.get("span_label"),
            "session_count": count,
            "total_distance_m": total_distance,
            "sample_insufficient": sample_insufficient,
        },
        "charts": charts,
    }


def build_trend_datapack(
    repo: SwimRepository,
    span: str,
    *,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    """完整装包：窗口场次 + 已算 metrics。"""
    raw = load_trend_raw(repo, span, end_time=end_time)
    metrics = compute_trend_metrics(raw)
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


def create_trend_analysis_agent(settings: Settings | None = None):
    """创建趋势分析 Agent（仅 Structured output，无工具）。"""
    settings = settings or load_settings()
    model = _chat_model(settings)
    return create_agent(
        model=model,
        tools=[],
        system_prompt=(
            "你是游泳趋势分析写手。输入已含窗口场次列表与代码算好的 metrics（含 charts 点列）。"
            "只根据 metrics 与分知识填写 TrendAnalysisReport："
            "headline + pages（overview/progress/load/next_step）+ chart_notes。"
            "若 metrics.sample_insufficient 为 true：headline.one_liner 必须点明「样本不足」，"
            "progress/load 的 notes 只做弱描述，不下强进步/伤病结论。"
            "页上数字来自 metrics，改写成短 label/value，不要发明新数字。"
            "chart_notes 对照 metrics.charts 各序列写一句说明，供折线图下方展示。"
            f"\n\n{_DIMENSION_KNOWLEDGE}"
        ),
        response_format=ToolStrategy(TrendAnalysisReport),
    )


def run_trend_analysis(
    repo: SwimRepository,
    span: str,
    settings: Settings | None = None,
    *,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    """装包 → 调用 Agent → 返回报告 dict。"""
    settings = settings or load_settings()
    datapack = build_trend_datapack(repo, span, end_time=end_time)
    agent = create_trend_analysis_agent(settings)
    user_payload = json.dumps(datapack, ensure_ascii=False, default=str)
    _LOGGER.info(
        "trend analysis start span=%s sessions=%s insufficient=%s",
        span,
        datapack["metrics"]["session_count"],
        datapack["metrics"]["sample_insufficient"],
    )
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"请生成趋势分析报告。span={span}，template_id 必须是 {TEMPLATE_ID}。\n"
                        f"数据包如下：\n{user_payload}"
                    ),
                }
            ]
        }
    )
    report = result.get("structured_response")
    if report is None:
        raise RuntimeError("趋势分析未返回 structured_response")
    if isinstance(report, BaseModel):
        data = report.model_dump()
    else:
        data = dict(report)
    data["span"] = span
    data["template_id"] = TEMPLATE_ID
    display = datapack["metrics"]["display"]
    headline = data.setdefault("headline", {})
    if isinstance(headline, dict):
        headline["span_label"] = display.get("span_label")
        headline["session_count"] = display.get("session_count")
        headline["total_distance_m"] = display.get("total_distance_m")
        headline["sample_insufficient"] = bool(display.get("sample_insufficient"))

    # 折线数值一律用代码序列；把模型写的说明挂到每张图上，供设计稿「SWOLF趋势」类页面渲染
    charts = datapack["metrics"].get("charts") or build_chart_series(datapack.get("sessions") or [])
    notes = data.pop("chart_notes", None) or {}
    if isinstance(notes, BaseModel):
        notes = notes.model_dump()
    for key in ("swolf", "pace", "distance"):
        chart = charts.get(key) or {}
        chart["note"] = (notes.get(key) if isinstance(notes, dict) else None) or ""
        charts[key] = chart
    data["charts"] = charts

    _LOGGER.info(
        "trend analysis done span=%s pages=%s chart_pts=%s",
        span,
        len(data.get("pages") or []),
        len((charts.get("swolf") or {}).get("points") or []),
    )
    return data


def report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
