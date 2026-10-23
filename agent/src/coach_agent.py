# 模块级说明：主教练（主 Agent）。
# 调用链：用户提问 → create_coach_agent 挂载的 ask_swim_database → SQL 子代理返回行 → 口语回答。
# Skills：启动挂 name/description；每线程首次用 pinned_skills 钉入 swim-coach 的 SKILL.md 正文；
# references/ 仍按主循环 read_file 按需加载。系统提示不含技能全文硬塞。
# 框架暂用 Deep Agents；SQL 查询实现见 src/sql_agent.py。

from __future__ import annotations

import contextvars
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterator

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents.middleware import AgentMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from src.config import Settings
from src.repository.swim_repo import SwimRepository
from src.sql_agent import build_swim_sql_tool

# =============================================================================
# 1. 常量与路径
# =============================================================================

# 逐行注释：默认会话线程 id；CLI / 设备可覆盖。
DEFAULT_THREAD_ID = "default-session"
# 逐行注释：与 skills/swim-coach/ 目录名、SKILL.md frontmatter name 一致。
SKILL_NAME = "swim-coach"
# 逐行注释：agent 包根；其下 skills/ 以虚拟路径 /skills/ 暴露给 Deep Agents。
AGENT_ROOT = Path(__file__).resolve().parents[1]
# 逐行注释：查库工具名；流式里用来触发等待语。
_QUERY_TOOL = "ask_swim_database"
# 逐行注释：设备/CLI 在开始查库时展示的固定句。
COACH_WAIT_LINE = "好的，请稍等，我先查询一下数据。\n"
_LOGGER = logging.getLogger("swim_coach")


# =============================================================================
# 2. 主教练短系统提示（仅硬约束，不含 SKILL 全文）
# =============================================================================
# swim-coach 正文（SKILL.md）由会话入口 pinned_skills 钉入；主题卡等 references 按需 read_file。


# 逐行注释：主从契约；口语与回合细节在已钉入的 skill 正文里，这里不重复堆叠。
SHORT_COACH_CONTRACT = (
    "你是业余游泳教练，根据佳明数据做中文口语分析和建议。"
    "会话里已钉入 swim-coach 技能正文时：严格按其中主循环作答；"
    "正文已含回合/意图/口语/可查口径，不要再为这些去 read_file references。"
    "仅在本轮要做单点分析或 CSS 时，才 read_file 一张主题卡或 css.md。"
    "不要凭通用知识写长篇报告。"
    "需要训练数字时：先调用 ask_swim_database，参数只写查询意图，拿到返回行后再开口。"
    "不要自己写 SQL，不要只说「我来查一下」就结束，不要编造数字。"
    "打招呼不查库。档案用 save_profile_fields / query_athlete_state；"
    "CSS 用 query_css_anchor / save_css_anchor。"
    "不要调用 task、write_file、edit_file、delete、execute。"
    "只回答刚刚这一句，不要复述历史。"
)


def build_system_prompt() -> str:
    """返回主教练短硬约束（不含技能正文）。"""
    # 逐行注释：正文靠 pinned_skills 注入，不在此粘贴 SKILL.md。
    return SHORT_COACH_CONTRACT


class _NoConversationSummary(AgentMiddleware):
    """关掉框架默认英文会话摘要，避免流进用户回复。"""

    @property
    def name(self) -> str:
        # 逐行注释：与 Deep Agents 默认摘要中间件同名，创建时按名替换。
        return "SummarizationMiddleware"


# =============================================================================
# 3. 创建主教练：显式挂载 ask_swim_database（SQL 子代理入口）
# =============================================================================
# 调用关系（一眼能看见主→SQL）：
#   create_coach_agent
#     → build_swim_sql_tool(model, repo) 得到 ask_swim_database
#     → 与档案/CSS 工具一起传入 create_deep_agent(tools=..., skills=["/skills/"])
#   运行时主 Agent tool_call ask_swim_database(查询意图)
#     → sql_agent：刷新视图 → 写 SQL → 安全执行 → 返回行
#   主教练按结果行说中文口语（不写 SQL）


def create_coach_agent(
    settings: Settings,
    tools: list[Any],
    repo: SwimRepository | None = None,
    checkpointer: Any | None = None,
):
    """创建主教练 Deep Agent，并挂上 SQL 子代理工具。"""
    # 逐行注释：没有仓库就无法挂 SQL 子代理。
    if repo is None:
        raise ValueError("创建教练需要 SwimRepository，以便挂载 SQL 子代理。")
    # 逐行注释：主 / SQL 共用同一模型客户端。
    model = ChatOpenAI(
        model=settings.model_name,
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        temperature=0.2,
        max_tokens=1024,
    )
    # 逐行注释：★ SQL 子代理在这里挂上。主教练只看见 ask_swim_database 这一个查数工具。
    sql_tool = build_swim_sql_tool(model, repo)
    all_tools = [*tools, sql_tool]
    if checkpointer is None:
        checkpointer = InMemorySaver()
    # 逐行注释：技能与参考卡只读文件系统（官方 Skills 后端）。
    backend = FilesystemBackend(root_dir=str(AGENT_ROOT), virtual_mode=True)
    filesystem = FilesystemMiddleware(
        backend=backend,
        tools=["ls", "read_file", "glob", "grep"],
    )
    # 逐行注释：Deep Agents 组装主教练；skills 目录提供元数据；正文见会话入口 pin。
    agent = create_deep_agent(
        model=model,
        tools=all_tools,
        system_prompt=build_system_prompt(),
        backend=backend,
        skills=["/skills/"],
        middleware=[filesystem, _NoConversationSummary()],
        checkpointer=checkpointer,
    )
    return agent


# =============================================================================
# 4. 会话入口：同步 / 流式（首次 pin swim-coach 的 SKILL.md 正文）
# =============================================================================


def _thread_config(thread_id: str) -> dict[str, Any]:
    """短期记忆线程配置。"""
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def _skill_already_pinned(agent: Any, thread_id: str) -> bool:
    """本线程消息里是否已有 swim-coach 的 pinned_skill 快照。"""
    # 逐行注释：只 pin 一次，避免每轮再追加一份 SKILL 正文占 token。
    try:
        snapshot = agent.get_state(_thread_config(thread_id))
    except Exception:
        return False
    values = getattr(snapshot, "values", None) or {}
    for message in values.get("messages") or []:
        extra = getattr(message, "additional_kwargs", None) or {}
        if extra.get("lc_source") != "pinned_skill":
            continue
        skill = extra.get("skill") or {}
        if skill.get("name") == SKILL_NAME:
            return True
    return False


def _turn_input(agent: Any, user_text: str, thread_id: str) -> dict[str, Any]:
    """组装本轮输入；线程首次对话时 pin swim-coach（即 SKILL.md 正文）。"""
    # 逐行注释：官方用法：pinned_skills 在下一轮模型调用前把 SKILL.md 去 frontmatter 后钉进对话。
    payload: dict[str, Any] = {"messages": [{"role": "user", "content": user_text}]}
    if not _skill_already_pinned(agent, thread_id):
        payload["pinned_skills"] = [SKILL_NAME]
        _LOGGER.info("pin skill=%s thread=%s", SKILL_NAME, thread_id)
    return payload


def ask_agent(agent: Any, user_text: str, thread_id: str = DEFAULT_THREAD_ID) -> dict[str, Any]:
    """同步调用主教练。"""
    # 逐行注释：只传用户原话；首次附带 pinned_skills。
    return agent.invoke(
        _turn_input(agent, user_text, thread_id),
        _thread_config(thread_id),
    )


def ask_agent_stream(agent: Any, user_text: str, thread_id: str = DEFAULT_THREAD_ID) -> Iterator[str]:
    """流式调用主教练，只产出可展示的口语片段。"""
    # 逐行注释：入口在块 4；过滤逻辑在块 5。
    input_payload = _turn_input(agent, user_text, thread_id)
    spoken = ""
    held = ""
    stopped = False
    said_wait = False
    pending_tool_name = ""
    sql_filter = _SqlLeakFilter()
    skipped_old = 0
    tool_names: list[str] = []
    for event in agent.stream(input_payload, _thread_config(thread_id), stream_mode="messages"):
        chunk = event[0] if isinstance(event, tuple) and event else event
        if _is_tool_message(chunk):
            continue
        if not _is_live_coach_token(chunk):
            skipped_old += 1
            continue
        # 逐行注释：主 Agent 开始调用 ask_swim_database 时立刻出等待语。
        tool_chunks = getattr(chunk, "tool_call_chunks", None) or []
        if not said_wait:
            for item in tool_chunks:
                tool_name = item.get("name") if isinstance(item, dict) else getattr(item, "name", "") or ""
                if not tool_name:
                    continue
                pending_tool_name += tool_name
                if _QUERY_TOOL in pending_tool_name:
                    said_wait = True
                    _LOGGER.info("tool %s thread=%s", _QUERY_TOOL, thread_id)
                    yield COACH_WAIT_LINE
                    break
                if pending_tool_name and pending_tool_name not in tool_names:
                    tool_names.append(pending_tool_name)
                    _LOGGER.info("tool %s thread=%s", pending_tool_name, thread_id)
        content = getattr(chunk, "content", "")
        text = sql_filter.feed(_normalize_chunk_text(content))
        if not text:
            continue
        spoken += text
        held += text
        if _is_internal_summary(spoken):
            stopped = True
            yield "\n（英文内部摘要已拦住，请再问一次）"
            break
        if _is_paragraph_loop(spoken):
            stopped = True
            yield "\n（后面开始重复，已停止）"
            break
        if _is_summary_heading_prefix(held):
            continue
        yield held
        held = ""
    if not stopped:
        tail = sql_filter.flush()
        if tail:
            held += tail
    if held and not stopped:
        yield held
    _LOGGER.info(
        "model done thread=%s skipped_old=%d tools=%s stopped=%s",
        thread_id,
        skipped_old,
        ",".join(tool_names) if tool_names else "-",
        stopped,
    )


# =============================================================================
# 5. 流式过滤与设备「开始查库」通知（次要，与编排分开）
# =============================================================================

_SUMMARY_HEADINGS = ("## SESSION INTENT", "## SUMMARY")
_SQL_OPENERS = ("select", "with", "```sql", "```sqlite")
_query_notifier: contextvars.ContextVar[Callable[[], None] | None] = contextvars.ContextVar(
    "coach_query_notifier", default=None
)


def bind_query_notifier(callback: Callable[[], None]) -> contextvars.Token:
    """登记本轮「开始查数据」监听。"""
    return _query_notifier.set(callback)


def reset_query_notifier(token: contextvars.Token) -> None:
    """拆掉本轮监听。"""
    _query_notifier.reset(token)


def notify_query_started() -> None:
    """SQL 子代理一进入 ask_swim_database 就通知外层（设备显示正在查询）。"""
    callback = _query_notifier.get()
    if callback is None:
        return
    callback()


def _normalize_chunk_text(content: Any) -> str:
    """把 chunk content 收成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _is_tool_message(chunk: Any) -> bool:
    """跳过工具返回，避免 JSON 进 TTS。"""
    msg_type = getattr(chunk, "type", "") or getattr(chunk, "role", "")
    if msg_type == "tool":
        return True
    return type(chunk).__name__ == "ToolMessage"


def _is_live_coach_token(chunk: Any) -> bool:
    """只收流式新字；历史 HumanMessage/AIMessage 整段丢掉。"""
    return type(chunk).__name__ == "AIMessageChunk"


def _is_paragraph_loop(text: str) -> bool:
    """相邻两段长文完全相同则截断。"""
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    if len(parts) < 2:
        return False
    return parts[-1] == parts[-2] and len(parts[-1]) >= 40


def _is_internal_summary(text: str) -> bool:
    """拦住框架英文摘要模板。"""
    return "SESSION INTENT" in text or ("## SUMMARY" in text and "## ARTIFACTS" in text)


def _is_summary_heading_prefix(text: str) -> bool:
    """缓冲是否仍可能是摘要标题前缀。"""
    sample = text.lstrip("\n")
    if not sample:
        return False
    return any(heading.startswith(sample) for heading in _SUMMARY_HEADINGS)


class _SqlLeakFilter:
    """从流式正文去掉漏出的 SQL。"""

    def __init__(self) -> None:
        self._carry = ""
        self._dropping = False

    def feed(self, text: str) -> str:
        data = self._carry + text
        self._carry = ""
        if self._dropping:
            return self._drop_until_chinese(data)
        while data:
            stripped = data.lstrip(" \t\r\n")
            if not stripped:
                self._carry = data
                break
            lower = stripped.lower()
            if any(lower.startswith(opener) for opener in _SQL_OPENERS):
                self._dropping = True
                return self._drop_until_chinese(stripped)
            if any(opener.startswith(lower) for opener in _SQL_OPENERS) and "\n" not in stripped:
                self._carry = data
                break
            return data
        return ""

    def _drop_until_chinese(self, data: str) -> str:
        match = re.search(r"[\u4e00-\u9fff]", data)
        if match is None:
            return ""
        self._dropping = False
        return self.feed(data[match.start() :])

    def flush(self) -> str:
        if self._dropping:
            self._carry = ""
            self._dropping = False
            return ""
        text = self._carry
        self._carry = ""
        sample = text.lstrip().lower()
        if sample and any(opener.startswith(sample) or sample.startswith(opener) for opener in _SQL_OPENERS):
            return ""
        return text
