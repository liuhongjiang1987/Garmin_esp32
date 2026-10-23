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
    # 逐行注释：已有 coach.db 也要补齐新表（如 css_anchors），避免 OperationalError。
    init_coach_db(settings.coach_db_path)
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


_VALIDATE_CASES = [
    # ── M1 效率纠偏 ──
    {
        "id": "M1-01",
        "tag": "M1",
        "question": "最近一场自由泳效率怎么样？",
        "must_not_contain": ["越小越好"],
        "note": "不应无条件说越小越好",
    },
    {
        "id": "M1-02",
        "tag": "M1",
        "question": "最近三场效率有没有进步？",
        "should_contain_any": ["同", "对照", "对比", "相近配速"],
        "note": "谈进步时应提到对照条件",
    },
    {
        "id": "M1-03",
        "tag": "M1",
        "question": "我的 SWOLF 比上次低了，但感觉配速变慢了，是进步了吗？",
        "should_contain_any": ["刷", "滑行", "过长", "试探", "再测", "相近配速"],
        "note": "配速变慢 SWOLF 变好时应试探刷分",
    },
    # ── M1 查询机制 ──
    {
        "id": "M1-04",
        "tag": "M1",
        "question": "查询我最近三次游泳的总体表现。",
        "must_not_contain": ["我来帮你查一下"],
        "note": "应实际调用工具查库，不能只回一句承诺",
    },
    # ── M2 CSS 无锚点 ──
    {
        "id": "M2-01",
        "tag": "M2",
        "question": "我该怎么练？",
        "should_contain_any": ["CSS", "临界", "测试", "400", "配速"],
        "note": "无锚点时应引导测试或自报 CSS",
    },
    {
        "id": "M2-02",
        "tag": "M2",
        "question": "什么是 CSS？",
        "should_contain_any": ["临界", "强度", "配速", "锚"],
        "note": "应简要解释 CSS 概念",
    },
    # ── M2 CSS 存锚点 ──
    {
        "id": "M2-03",
        "tag": "M2",
        "question": "我的 CSS 大概 2 分钟每 100 米，400+200 自测的。",
        "should_contain_any": ["Z", "区", "有氧", "阈值"],
        "note": "应保存锚点并报出训练区",
    },
    # ── M2 三条处方 ──
    {
        "id": "M2-04",
        "tag": "M2",
        "question": "展开讲讲这周怎么练。",
        "should_contain_any": ["复测", "周"],
        "must_not_contain": ["第四条", "第五条"],
        "note": "最多三条组次，必须提复测",
    },
    # ── 基础功能 ──
    {
        "id": "BASE-01",
        "tag": "基础",
        "question": "你好小智",
        "must_not_contain": ["ask_swim_database", "SQL", "SELECT"],
        "note": "打招呼不查库",
    },
    {
        "id": "BASE-02",
        "tag": "基础",
        "question": "最近一场游了多远？",
        "should_contain_any": ["米", "距离"],
        "note": "简单数据查询应正常返回",
    },
]


def cmd_validate() -> None:
    """执行 M1/M2 验收回归。每条打印通过或失败。"""
    settings = load_settings()
    repo = build_repo()
    tools = build_tools(repo)

    try:
        agent = create_coach_agent(settings=settings, tools=tools, repo=repo)
    except Exception as exc:
        print(f"[FATAL] 创建教练失败: {type(exc).__name__}: {exc}")
        return

    thread_id = f"validate-{uuid.uuid4().hex[:8]}"
    passed = 0
    failed = 0
    errors: list[str] = []

    for case in _VALIDATE_CASES:
        cid = case["id"]
        q = case["question"]
        print(f"\n{'='*50}")
        print(f"[{cid}] {case['tag']} | {case['note']}")
        print(f"  Q: {q}")

        try:
            answer = ""
            for token in ask_agent_stream(agent, q, thread_id=thread_id):
                answer += token
            print(f"  A: {answer[:300]}")
        except Exception as exc:
            print(f"  ✗ 调用失败: {type(exc).__name__}: {exc}")
            failed += 1
            errors.append(f"{cid}: 调用失败")
            continue

        # 检查 must_not_contain
        fail_reasons: list[str] = []
        for bad in case.get("must_not_contain", []):
            if bad in answer:
                fail_reasons.append(f"不应包含「{bad}」")

        # 检查 should_contain_any
        keywords = case.get("should_contain_any", [])
        if keywords and not any(kw in answer for kw in keywords):
            fail_reasons.append(f"应包含其中之一: {keywords}")

        if fail_reasons:
            for r in fail_reasons:
                print(f"  ✗ {r}")
            failed += 1
            errors.append(f"{cid}: {'; '.join(fail_reasons)}")
        else:
            print(f"  ✓ 通过")
            passed += 1

    print(f"\n{'='*50}")
    print(f"结果: {passed} 通过, {failed} 失败, 共 {len(_VALIDATE_CASES)} 条")
    if errors:
        print("失败项:")
        for e in errors:
            print(f"  - {e}")


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

