# 模块级说明：本地 CLI。
# 单次：after-sync 预分析；趋势：request-trend 点选入队，再 process-jobs / 后台跑。
# analyze-* 仅开发调试。

from __future__ import annotations

import argparse
import json
import logging

from src.analysis_queue import (
    after_sync,
    enqueue_session_jobs,
    get_session_report,
    get_trend_report,
    get_trend_status,
    list_sessions_for_ui,
    list_trends_for_ui,
    process_session_jobs,
    process_trend_jobs,
    request_trend_analysis,
)
from src.analytics.pipeline import run_activity_analytics
from src.config import load_settings
from src.db.schema import init_coach_db
from src.repository.swim_repo import DbPaths, SwimRepository
from src.session_analysis_agent import run_session_analysis
from src.trend_analysis_agent import SPAN_DEFS, run_trend_analysis

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def build_repo() -> SwimRepository:
    settings = load_settings()
    init_coach_db(settings.coach_db_path)
    return SwimRepository(
        DbPaths(
            coach_db=settings.coach_db_path,
            garmin_db=settings.garmin_db_path,
            garmin_activities_db=settings.garmin_activities_db_path,
        )
    )


def cmd_init() -> None:
    settings = load_settings()
    init_coach_db(settings.coach_db_path)
    repo = build_repo()
    evidence = run_activity_analytics(
        repo,
        settings.csv_sample_path,
        activity_id="638297383",
    )
    repo.upsert_profile(
        "default",
        {
            "athlete_id": "default",
            "goal": "improve_swim_efficiency",
            "weekly_sessions": 3,
        },
    )
    print("init done")
    print(json.dumps({"activity_id": "638297383", "labels": evidence["l2"]["labels"]}, ensure_ascii=False))


def cmd_analytics(activity_id: str) -> None:
    settings = load_settings()
    repo = build_repo()
    evidence = run_activity_analytics(
        repo,
        settings.csv_sample_path,
        activity_id=activity_id,
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


def cmd_after_sync(session_limit: int, trend_limit: int) -> None:
    """同步后：单次入队处理 + 作废趋势缓存（不预跑九档）。"""
    settings = load_settings()
    repo = build_repo()
    result = after_sync(repo, settings, session_limit=session_limit, trend_limit=trend_limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_process_jobs(session_limit: int, trend_limit: int) -> None:
    """消化单次队列 + 用户已点选的趋势任务。"""
    settings = load_settings()
    repo = build_repo()
    enqueue_session_jobs(repo)
    print(
        json.dumps(
            {
                "session": process_session_jobs(repo, settings, limit=session_limit),
                "trend": process_trend_jobs(repo, settings, limit=trend_limit),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_request_trend(span: str, *, run_now: bool) -> None:
    """模拟点选跨度：入队；可选立刻跑完。"""
    settings = load_settings()
    repo = build_repo()
    result = request_trend_analysis(repo, span)
    if run_now and result["status"] == "analyzing":
        stats = process_trend_jobs(repo, settings, limit=1, only_span=span)
        result = {**get_trend_status(repo, span), "process": stats, "started": result.get("started")}
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_trend_status(span: str) -> None:
    repo = build_repo()
    print(json.dumps(get_trend_status(repo, span), ensure_ascii=False, indent=2))


def cmd_list_sessions() -> None:
    """打印表盘会看到的列表状态。"""
    repo = build_repo()
    print(json.dumps(list_sessions_for_ui(repo), ensure_ascii=False, indent=2))


def cmd_show_report(activity_id: str) -> None:
    """只读已入库报告（未完成则提示）。"""
    repo = build_repo()
    report = get_session_report(repo, activity_id)
    if report is None:
        items = {i["activity_id"]: i for i in list_sessions_for_ui(repo, limit=200)}
        item = items.get(activity_id)
        if item:
            print(json.dumps({"ok": False, "status": item["status"], "can_open": False}, ensure_ascii=False))
        else:
            print(json.dumps({"ok": False, "error": "not_found"}, ensure_ascii=False))
        return
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_list_trends() -> None:
    repo = build_repo()
    print(json.dumps(list_trends_for_ui(repo), ensure_ascii=False, indent=2))


def cmd_show_trend_report(span: str) -> None:
    """只读已入库趋势报告（模拟点开 ✓ 跨度）。"""
    repo = build_repo()
    report = get_trend_report(repo, span)
    if report is None:
        items = {i["span"]: i for i in list_trends_for_ui(repo)}
        item = items.get(span)
        if item:
            print(json.dumps({"ok": False, "status": item["status"], "can_open": False}, ensure_ascii=False))
        else:
            print(json.dumps({"ok": False, "error": "not_found"}, ensure_ascii=False))
        return
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_analyze_session_debug(activity_id: str | None) -> None:
    """开发调试：不经队列直接跑 Agent（不写产品状态机时用）。"""
    settings = load_settings()
    repo = build_repo()
    aid = activity_id or repo.get_latest_swim_activity_id()
    if not aid:
        print("没有可用的游泳活动")
        return
    report = run_session_analysis(repo, aid, settings=settings)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_analyze_trend_debug(span: str) -> None:
    settings = load_settings()
    repo = build_repo()
    report = run_trend_analysis(repo, span, settings=settings)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_serve() -> None:
    import os

    import uvicorn

    from src.api import create_app

    # 默认监听全网卡，供同局域网 ESP32 访问；本机调试可设 COACH_BIND=127.0.0.1
    host = os.getenv("COACH_BIND", "0.0.0.0")
    port = int(os.getenv("COACH_PORT", "8765"))
    uvicorn.run(create_app(), host=host, port=port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Swim analysis CLI (v2 queue)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="init coach db and seed evidence")
    analytics_parser = sub.add_parser("analytics", help="compute evidence for one CSV activity")
    analytics_parser.add_argument("--activity-id", default="638297383")

    after = sub.add_parser("after-sync", help="session enqueue + invalidate trend cache")
    after.add_argument("--session-limit", type=int, default=10)
    after.add_argument("--trend-limit", type=int, default=1)

    proc = sub.add_parser("process-jobs", help="process session + on-demand trend jobs")
    proc.add_argument("--session-limit", type=int, default=10)
    proc.add_argument("--trend-limit", type=int, default=3)

    sub.add_parser("list-sessions", help="UI list with analyzing/succeeded status")
    show = sub.add_parser("show-report", help="read stored session report only")
    show.add_argument("--activity-id", required=True)
    sub.add_parser("list-trends", help="UI trend spans (idle until clicked)")
    req_t = sub.add_parser("request-trend", help="click a span: enqueue analyzing")
    req_t.add_argument("--span", required=True, choices=sorted(SPAN_DEFS.keys()))
    req_t.add_argument("--run", action="store_true", help="process this span now")
    st_t = sub.add_parser("trend-status", help="poll trend analyzing page")
    st_t.add_argument("--span", required=True, choices=sorted(SPAN_DEFS.keys()))
    show_t = sub.add_parser("show-trend-report", help="read stored trend report only")
    show_t.add_argument("--span", required=True, choices=sorted(SPAN_DEFS.keys()))

    dbg_s = sub.add_parser("analyze-session", help="DEBUG: run agent now (bypass queue write path)")
    dbg_s.add_argument("--activity-id", default=None)
    dbg_t = sub.add_parser("analyze-trend", help="DEBUG: run trend agent now")
    dbg_t.add_argument("--span", default="1m", choices=sorted(SPAN_DEFS.keys()))

    sub.add_parser("serve", help="start HTTP API")

    args = parser.parse_args()
    if args.cmd == "init":
        cmd_init()
    elif args.cmd == "analytics":
        cmd_analytics(args.activity_id)
    elif args.cmd == "after-sync":
        cmd_after_sync(args.session_limit, args.trend_limit)
    elif args.cmd == "process-jobs":
        cmd_process_jobs(args.session_limit, args.trend_limit)
    elif args.cmd == "list-sessions":
        cmd_list_sessions()
    elif args.cmd == "show-report":
        cmd_show_report(args.activity_id)
    elif args.cmd == "list-trends":
        cmd_list_trends()
    elif args.cmd == "request-trend":
        cmd_request_trend(args.span, run_now=args.run)
    elif args.cmd == "trend-status":
        cmd_trend_status(args.span)
    elif args.cmd == "show-trend-report":
        cmd_show_trend_report(args.span)
    elif args.cmd == "analyze-session":
        cmd_analyze_session_debug(args.activity_id)
    elif args.cmd == "analyze-trend":
        cmd_analyze_trend_debug(args.span)
    elif args.cmd == "serve":
        cmd_serve()


if __name__ == "__main__":
    main()
