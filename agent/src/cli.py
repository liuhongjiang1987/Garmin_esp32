# 模块级说明：提供本地开发期 CLI，执行初始化、重算与交互对话。

from __future__ import annotations

import argparse
import json
import os
import sys

import uuid

from src.agent_runtime import ask_agent, ask_agent_stream, create_coach_agent
from src.analytics.pipeline import run_activity_analytics
from src.config import load_settings
from src.db.schema import init_coach_db
from src.repository.swim_repo import DbPaths, SwimRepository
from src.tools import build_tools


def build_repo() -> SwimRepository:
    """构建仓库对象。"""
    settings = load_settings()
    return SwimRepository(
        DbPaths(
            coach_db=settings.coach_db_path,
            garmin_db=settings.garmin_db_path,
            garmin_activities_db=settings.garmin_activities_db_path,
        )
    )


def cmd_init() -> None:
    """初始化 coach.db 并导入样例 evidence。"""
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
    """手动触发分析。"""
    settings = load_settings()
    repo = build_repo()
    evidence = run_activity_analytics(
        repo,
        settings.csv_sample_path,
        activity_id=activity_id,
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


def cmd_serve() -> None:
    """在本机启动内网文字接口。默认只接受这台电脑自己的访问。"""
    import uvicorn

    from src.api import create_app

    host = os.getenv("COACH_BIND", "127.0.0.1")
    port = int(os.getenv("COACH_PORT", "8765"))
    uvicorn.run(create_app(), host=host, port=port)


def cmd_chat() -> None:
    """进入交互式对话（单 ReAct Agent + 短期记忆）。"""
    settings = load_settings()
    repo = build_repo()
    # 逐行注释：档案和采访工具。训练数据工具在创建教练时挂上。
    tools = build_tools(repo)
    # 逐行注释：创建带 checkpointer 与数据接地的单 Agent。
    agent = create_coach_agent(settings=settings, tools=tools, repo=repo)
    # 逐行注释：为本次会话分配唯一 thread_id，供多轮短期记忆续接。
    thread_id = f"cli-{uuid.uuid4().hex[:8]}"

    print("swim coach agent ready, 输入 q 退出")
    while True:
        try:
            user_text = input("你> ").strip()
        except KeyboardInterrupt:
            # 逐行注释：在等待输入时 Ctrl+C，直接结束会话，不打印调用栈。
            print()
            break
        if user_text.lower() in {"q", "quit", "exit"}:
            break
        print("教练> ", end="", flush=True)
        has_output = False
        failed = False
        try:
            for token_text in ask_agent_stream(agent, user_text, thread_id=thread_id):
                has_output = True
                print(token_text, end="", flush=True)
        except KeyboardInterrupt:
            # 逐行注释：生成过程中 Ctrl+C 只停本轮，回到下一轮输入。
            print("\n（已停止本轮输出）", end="")
            failed = True
        except Exception as exc:
            # 逐行注释：限流或其他接口错误时留在对话循环里，避免整段会话被 traceback 打断。
            failed = True
            name = type(exc).__name__
            if name == "RateLimitError" or getattr(exc, "status_code", None) == 429:
                print("\n（接口限流，请稍等再问）", end="")
            else:
                print(f"\n（本轮失败：{name}，请重试）", end="")
        if not has_output and not failed:
            # 逐行注释：若上游未返回流式 token，给出可感知提示。
            print("(未收到流式输出，请重试)", end="", flush=True)
        print()
        sys.stdout.flush()


def cmd_validate() -> None:
    """执行最小验收问句回归。"""
    settings = load_settings()
    repo = build_repo()
    tools = build_tools(repo)
    questions = [
        "今天总共游了多远、多久？",
        "主泳姿是什么？",
        "哪一组掉速最明显？",
        "休息时心率回落怎么样？",
        "给我一句今天的训练结论。",
    ]
    try:
        agent = create_coach_agent(settings=settings, tools=tools, repo=repo)
        for q in questions:
            result = ask_agent(agent, q)
            messages = result.get("messages", [])
            final_text = ""
            for msg in reversed(messages):
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content:
                    final_text = content
                    break
            print(f"[Q] {q}")
            print(f"[A] {final_text}")
            print("-" * 40)
    except Exception as exc:
        print("[WARN] 在线LLM回归失败，切换到离线证据回归。")
        print(f"[WARN] {type(exc).__name__}: {exc}")
        activity_id = repo.get_latest_swim_activity_id() or "638297383"
        summary = repo.get_activity_summary(activity_id)
        evidence = repo.get_evidence(activity_id)
        checks = {
            "has_summary": summary is not None,
            "has_evidence": evidence is not None,
            "has_labels": bool(evidence and evidence.get("l2", {}).get("labels")),
            "distance_positive": bool(evidence and evidence.get("l0", {}).get("total_distance_m", 0) > 0),
        }
        consistency = (evidence or {}).get("consistency_check", {})
        print(
            json.dumps(
                {
                    "activity_id": activity_id,
                    "checks": checks,
                    "consistency_check": consistency,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="Swim coach agent CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="init coach db and seed evidence")

    analytics_parser = sub.add_parser("analytics", help="run analytics for one activity")
    analytics_parser.add_argument("--activity-id", default="638297383")

    sub.add_parser("chat", help="interactive chat")
    sub.add_parser("serve", help="start the text API")
    sub.add_parser("validate", help="run quick validation prompts")

    args = parser.parse_args()
    if args.cmd == "init":
        cmd_init()
    elif args.cmd == "analytics":
        cmd_analytics(args.activity_id)
    elif args.cmd == "chat":
        cmd_chat()
    elif args.cmd == "serve":
        cmd_serve()
    elif args.cmd == "validate":
        cmd_validate()


if __name__ == "__main__":
    main()

