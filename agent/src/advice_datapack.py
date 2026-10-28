# 模块说明：综合建议 Data pack——从已落库的单次/趋势报告预装「摘要卡」。
# 对齐 docs/2.0/三节目策略 §3.2：语音轮与出计划默认预装，不挂交互式 SQL Agent。

from __future__ import annotations

import json
import logging
from typing import Any

from src.analysis_queue import get_session_report, get_trend_report, list_sessions_for_ui
from src.repository.swim_repo import SwimRepository

_LOGGER = logging.getLogger("advice_datapack")

# 默认可注入计划 Agent 的近期场次 / 趋势跨度（墨水屏上下文要短）
DEFAULT_SESSION_LIMIT = 5
DEFAULT_TREND_SPANS = ("1W", "1M", "3M")


def _page_notes(pages: list[Any], page_id: str) -> str:
    for page in pages:
        if not isinstance(page, dict):
            continue
        if page.get("page_id") != page_id:
            continue
        notes = page.get("notes") or []
        texts = [str(n).strip() for n in notes if n]
        if texts:
            return "；".join(texts)[:120]
    return ""


def _headline_one_liner(report: dict[str, Any]) -> str:
    headline = report.get("headline") or {}
    if isinstance(headline, dict):
        text = headline.get("one_liner") or ""
        if text:
            return str(text)[:80]
    return str(report.get("one_liner") or "")[:80]


def session_report_to_card(activity_id: str, report: dict[str, Any], *, date: str = "") -> dict[str, Any]:
    """单次 AnalysisReport → 摘要卡（结构化，供计划 Agent 引用）。"""
    headline = report.get("headline") if isinstance(report.get("headline"), dict) else {}
    pages = report.get("pages") if isinstance(report.get("pages"), list) else []
    return {
        "kind": "session",
        "activity_id": activity_id,
        "date": date or str(headline.get("date") or ""),
        "one_liner": _headline_one_liner(report),
        "metrics": {
            "distance_m": headline.get("distance_m"),
            "pace_text": headline.get("pace_text"),
            "swolf": headline.get("swolf"),
        },
        "next_step": _page_notes(pages, "next_step"),
        "efficiency_note": _page_notes(pages, "efficiency"),
        "endurance_note": _page_notes(pages, "endurance"),
    }


def trend_report_to_card(span: str, report: dict[str, Any]) -> dict[str, Any]:
    """趋势 TrendAnalysisReport → 摘要卡。"""
    headline = report.get("headline") if isinstance(report.get("headline"), dict) else {}
    pages = report.get("pages") if isinstance(report.get("pages"), list) else []
    return {
        "kind": "trend",
        "span": span,
        "span_label": str(headline.get("span_label") or span),
        "one_liner": _headline_one_liner(report),
        "session_count": headline.get("session_count"),
        "total_distance_m": headline.get("total_distance_m"),
        "sample_insufficient": bool(headline.get("sample_insufficient")),
        "progress_note": _page_notes(pages, "progress"),
        "load_note": _page_notes(pages, "load"),
        "next_step": _page_notes(pages, "next_step"),
    }


def build_session_summary_cards(
    repo: SwimRepository,
    *,
    limit: int = DEFAULT_SESSION_LIMIT,
) -> list[dict[str, Any]]:
    """取近期已成功单次报告，压成摘要卡列表（时间新→旧）。"""
    cards: list[dict[str, Any]] = []
    try:
        items = list_sessions_for_ui(repo, limit=max(limit * 2, limit))
    except Exception:
        _LOGGER.exception("list sessions for advice cards failed")
        return cards
    for item in items:
        if not item.get("can_open"):
            continue
        activity_id = str(item.get("activity_id") or "")
        if not activity_id:
            continue
        try:
            report = get_session_report(repo, activity_id)
        except Exception:
            _LOGGER.exception("load session report %s failed", activity_id)
            continue
        if not report:
            continue
        cards.append(
            session_report_to_card(
                activity_id,
                report,
                date=str(item.get("date") or ""),
            )
        )
        if len(cards) >= limit:
            break
    return cards


def build_trend_summary_cards(
    repo: SwimRepository,
    spans: tuple[str, ...] = DEFAULT_TREND_SPANS,
) -> list[dict[str, Any]]:
    """取指定跨度已成功趋势报告 → 摘要卡。"""
    cards: list[dict[str, Any]] = []
    for span in spans:
        try:
            report = get_trend_report(repo, span)
        except Exception:
            _LOGGER.exception("load trend report %s failed", span)
            continue
        if not report:
            continue
        cards.append(trend_report_to_card(span, report))
    return cards


def build_advice_datapack(
    repo: SwimRepository,
    profile: dict[str, Any] | None = None,
    *,
    user_request: str | None = None,
    session_limit: int = DEFAULT_SESSION_LIMIT,
    trend_spans: tuple[str, ...] = DEFAULT_TREND_SPANS,
) -> dict[str, Any]:
    """
    综合建议出计划 / 语音轮用的 Data pack。

    - profile：持久档案
    - user_request：本轮诉求摘要（可空）
    - summary_cards.sessions / .trends：预装结构化结果（来自已算好的报告，不再现查 SQL）
    """
    sessions = build_session_summary_cards(repo, limit=session_limit)
    trends = build_trend_summary_cards(repo, spans=trend_spans)
    headlines = [c["one_liner"] for c in sessions[:2] if c.get("one_liner")]
    headlines += [c["one_liner"] for c in trends if c.get("one_liner")]
    return {
        "profile": profile or {},
        "user_request": user_request or "",
        "summary_cards": {
            "sessions": sessions,
            "trends": trends,
        },
        "headlines": headlines[:6],
        "meta": {
            "session_card_count": len(sessions),
            "trend_card_count": len(trends),
            "source": "precomputed_reports",
        },
    }


def datapack_prompt_blob(datapack: dict[str, Any]) -> str:
    """压缩给模型的 JSON 字符串（控制长度）。"""
    slim = {
        "profile": datapack.get("profile") or {},
        "user_request": datapack.get("user_request") or "",
        "headlines": datapack.get("headlines") or [],
        "summary_cards": datapack.get("summary_cards") or {},
    }
    text = json.dumps(slim, ensure_ascii=False)
    if len(text) > 6000:
        # 极端情况：只留 headline + 最近 2 场 + 趋势卡
        cards = slim.get("summary_cards") or {}
        slim["summary_cards"] = {
            "sessions": (cards.get("sessions") or [])[:2],
            "trends": cards.get("trends") or [],
        }
        text = json.dumps(slim, ensure_ascii=False)
    return text
