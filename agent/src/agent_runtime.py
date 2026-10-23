# 模块级说明：用 Deep Agents 组装游泳教练。流程和口语在 skill 里，业务工具挂在 create_deep_agent 上。

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

# 逐行注释：默认会话线程 id，CLI 可按会话覆盖，实现多轮短期记忆隔离。
DEFAULT_THREAD_ID = "default-session"

# 逐行注释：唯一教练技能目录名，对应 agent/skills/swim-coach/SKILL.md。
SKILL_NAME = "swim-coach"

# 逐行注释：agent 包根目录。其下 skills/ 由 FilesystemBackend 以虚拟路径 /skills/ 暴露。
AGENT_ROOT = Path(__file__).resolve().parents[1]


def _skill_body() -> str:
    """读取技能正文，去掉 YAML 头。参考卡不在这里，仍按需 read_file。"""
    # 逐行注释：每次创建 agent 时从磁盘读取，改完技能后重启对话即可生效。
    text = (AGENT_ROOT / "skills" / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
    # 逐行注释：frontmatter 只给技能目录用，不重复放进系统提示词。
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    return text.strip()


class _NoConversationSummary(AgentMiddleware):
    """替换框架默认摘要。默认摘要是英文 SESSION INTENT 模板，会直接流进用户看见的回复。"""

    @property
    def name(self) -> str:
        # 逐行注释：与 Deep Agents 默认摘要中间件同名，创建时按名称替换掉它。
        return "SummarizationMiddleware"


def build_system_prompt() -> str:
    """返回每轮都携带的系统提示词，其中包含 swim-coach 全文。"""
    # 逐行注释：框架的 pinned_skills 只会把正文追加进某一轮消息，摘要后会丢失。
    return (
        "你是一名面向业余游泳者的教练，根据佳明游泳数据做个体化分析和建议。"
        "对用户只说中文口语，不要写英文标题、会话摘要或任务清单。"
        "用户只是打招呼或叫你的名字时，只回一句简短问候，不要查数据库，也不要提训练数字。"
        "用户说了一长段，但没有点名配速、距离、SWOLF、划次、场次或五个主题之一时，不要调用任何工具，用一句话请他指定要查什么。"
        "只回答刚刚这一句。不要把以前的问题和回答再念一遍。"
        "需要训练数字时，第一步就是调用 ask_swim_database，不要先对用户说话。"
        "工具参数写成一条查询任务，例如「最近一场的距离、配速、SWOLF」。拿到工具返回后再开口。"
        "禁止只说「我来查一下」「稍等」就结束。不要自己写 SQL。"
        "档案工具另外挂载。不要调用 task、write_file、edit_file、delete、execute。"
        "下面是 swim-coach 技能全文，每一轮都必须遵守。主题参考卡按其中的路径用 read_file 按需读取，不要把参考卡当成已经加载。\n\n"
        + _skill_body()
    )


def create_coach_agent(
    settings: Settings,
    tools: list[Any],
    repo: SwimRepository | None = None,
    checkpointer: Any | None = None,
):
    """创建 Deep Agent。业务工具始终可见，SQL 子代理作为一个工具挂上。"""
    # 逐行注释：没有仓库就无法建立 SQL 子代理。
    if repo is None:
        raise ValueError("创建教练需要 SwimRepository，以便挂载 SQL 子代理。")
    # 逐行注释：构造 OpenAI 兼容模型客户端。
    model = ChatOpenAI(
        # 逐行注释：从环境变量注入模型名。
        model=settings.model_name,
        # 逐行注释：注入 API Key。
        api_key=settings.model_api_key,
        # 逐行注释：注入 OpenAI 兼容 base_url。
        base_url=settings.model_base_url,
        # 逐行注释：温度保持较低，减少复盘时的随机性。
        temperature=0.2,
        # 逐行注释：限制单次生成长度，避免重复句一直流到人工中断。
        max_tokens=1024,
    )
    # 逐行注释：SQL 子代理与教练共用模型，但只通过一个工具把结论交回来。
    tools = [*tools, build_swim_sql_tool(model, repo)]
    # 逐行注释：默认使用内存级 checkpointer，提供单进程内的多轮短期记忆。
    if checkpointer is None:
        checkpointer = InMemorySaver()
    # 逐行注释：技能和参考卡都在 agent/skills 下，虚拟路径限制在这个根目录内。
    backend = FilesystemBackend(root_dir=str(AGENT_ROOT), virtual_mode=True)
    # 逐行注释：替换默认文件系统工具，只保留读取，避免教练改文件或执行命令。
    filesystem = FilesystemMiddleware(
        backend=backend,
        tools=["ls", "read_file", "glob", "grep"],
    )
    # 逐行注释：业务工具走 tools 参数；技能目录只提供说明和知识卡。
    agent = create_deep_agent(
        # 逐行注释：传入模型实例。
        model=model,
        # 逐行注释：挂载查询、档案和保存工具。
        tools=tools,
        # 逐行注释：系统提示词每轮都带技能全文，不依赖某一轮的 pin 消息。
        system_prompt=build_system_prompt(),
        # 逐行注释：同一后端供技能读取和 read_file 使用。
        backend=backend,
        # 逐行注释：指向存放技能子目录的那一层，而不是某个 SKILL.md 所在目录。
        skills=["/skills/"],
        # 逐行注释：只读文件系统替换默认读写；空摘要中间件替换英文会话摘要。
        middleware=[filesystem, _NoConversationSummary()],
        # 逐行注释：挂载短期记忆。
        checkpointer=checkpointer,
    )
    # 逐行注释：返回可复用 agent。
    return agent


def _turn_input(user_text: str) -> dict[str, Any]:
    """组装本轮用户消息。技能全文在系统提示词里，不靠本轮消息携带。"""
    return {"messages": [{"role": "user", "content": user_text}]}


def _needs_swim_numbers(user_text: str) -> bool:
    """判断这句是否在要训练数字，需要强制走查库工具。"""
    # 逐行注释：纯打招呼不查库。
    compact = re.sub(r"[\s\W_]+", "", user_text, flags=re.UNICODE)
    greetings = {"你好小智", "你好", "您好", "在吗", "嗨", "哈喽", "hello", "hi", "小智"}
    if compact.lower() in greetings:
        return False
    # 逐行注释：这些词出现时，没有 ask_swim_database 就容易空口承诺或编造。
    cues = (
        "距离", "配速", "swolf", "SWOLF", "效率", "划次", "划水", "最近一场", "最近三",
        "最近几", "游了", "表现", "多少米", "心率", "休息", "前后半", "自由泳", "蛙泳",
        "仰泳", "蝶泳", "查一下", "查询", "多远", "多久", "趋势", "耐力", "负荷",
    )
    return any(cue in user_text for cue in cues)


def _with_tool_nudge(user_text: str) -> str:
    """需要数字时在用户消息后追加强制调工具提示，避免只说「我来查一下」。"""
    # 逐行注释：提示只给模型看，设备侧不会当作用户原话播报。
    if not _needs_swim_numbers(user_text):
        return user_text
    return (
        user_text
        + "\n\n（系统：本轮必须先调用 ask_swim_database，再根据返回数字回答。禁止只说我来查一下，禁止编造数字。）"
    )


def _thread_config(thread_id: str) -> dict[str, Any]:
    """构造带 thread_id 的调用配置，用于短期记忆续接。"""
    # 逐行注释：限制图的步数，避免一句空泛的长话把工具链跑到连接超时。
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def ask_agent(agent: Any, user_text: str, thread_id: str = DEFAULT_THREAD_ID) -> dict[str, Any]:
    """同步调用 Agent（带会话线程）。"""
    # 逐行注释：技能已在系统提示词中，这里只追加用户消息。
    return agent.invoke(
        _turn_input(_with_tool_nudge(user_text)),
        _thread_config(thread_id),
    )


def _normalize_chunk_text(content: Any) -> str:
    """把 chunk content 归一化为可打印文本。"""
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
    """判断该 chunk 是否为工具返回消息（工具 JSON 不应作为教练话术输出）。"""
    # 逐行注释：ToolMessage 的 type 为 "tool"；兼容 role 字段。
    msg_type = getattr(chunk, "type", "") or getattr(chunk, "role", "")
    if msg_type == "tool":
        return True
    # 逐行注释：类名兜底判断。
    return type(chunk).__name__ == "ToolMessage"


def _is_paragraph_loop(text: str) -> bool:
    """相邻两段非空正文完全相同，且足够长，视为模型陷入重复。"""
    # 逐行注释：按空行拆段，去掉空白段。
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    # 逐行注释：至少两段才可能形成循环。
    if len(parts) < 2:
        return False
    # 逐行注释：短句重复（如“好的”）不截断，只拦成段复制。
    return parts[-1] == parts[-2] and len(parts[-1]) >= 40


# 逐行注释：摘要标题的前缀先暂存，等能判断是不是英文模板再决定是否打印。
_SUMMARY_HEADINGS = ("## SESSION INTENT", "## SUMMARY")


def _is_internal_summary(text: str) -> bool:
    """框架英文摘要模板一旦出现，就不再继续往外送。"""
    # 逐行注释：标题可能被拆进前后两个流式片段，所以看累计文本。
    return "SESSION INTENT" in text or ("## SUMMARY" in text and "## ARTIFACTS" in text)


def _is_summary_heading_prefix(text: str) -> bool:
    """当前缓冲是否仍可能是英文摘要标题的开头。"""
    # 逐行注释：去掉前导换行后再比对，避免空行把标题推迟到下一片段。
    sample = text.lstrip("\n")
    if not sample:
        return False
    return any(heading.startswith(sample) for heading in _SUMMARY_HEADINGS)


# 逐行注释：子代理偶尔会把 SELECT 写进正文，这些开头用来识别并丢掉。
_SQL_OPENERS = ("select", "with", "```sql", "```sqlite")
# 逐行注释：只有开始查游泳数据库时才说这一句。问候和不查数的话不说。设备单独播报，不放进正式回答。
COACH_WAIT_LINE = "好的，请稍等，我先查询一下数据。\n"
_QUERY_TOOL = "ask_swim_database"
# 逐行注释：当前这一轮的监听函数。子代理一进入就调用它，不等查询结束。
_query_notifier: contextvars.ContextVar[Callable[[], None] | None] = contextvars.ContextVar(
    "coach_query_notifier", default=None
)


def bind_query_notifier(callback: Callable[[], None]) -> contextvars.Token:
    """记下这一轮谁来接收“开始查数据”的信号。"""
    # 逐行注释：放进上下文，同线程里的子代理工具才能看见。
    return _query_notifier.set(callback)


def reset_query_notifier(token: contextvars.Token) -> None:
    """这一轮结束后拆掉监听，避免串到下一句。"""
    # 逐行注释：用设置时返回的令牌还原，不用空回调覆盖。
    _query_notifier.reset(token)


def notify_query_started() -> None:
    """游泳数据子代理被调用时立刻通知外层。"""
    # 逐行注释：命令行没有监听时直接返回。
    callback = _query_notifier.get()
    if callback is None:
        return
    # 逐行注释：马上发出信号，后面的查库还没开始。
    callback()


class _SqlLeakFilter:
    """从流式正文里去掉 SQL，保留后面的中文。"""

    def __init__(self) -> None:
        # 逐行注释：可能只收到 SELECT 的前几个字母，先攒着再判断。
        self._carry = ""
        # 逐行注释：已经确认是 SQL 后，一直丢到出现中文。
        self._dropping = False

    def feed(self, text: str) -> str:
        """吃进一个流式片段，返回可以展示的部分。"""
        # 逐行注释：拼上上次没判断完的前缀。
        data = self._carry + text
        self._carry = ""
        # 逐行注释：正在丢 SQL 时，只等中文出现。
        if self._dropping:
            return self._drop_until_chinese(data)
        emitted: list[str] = []
        while data:
            # 逐行注释：只剥空白。反引号要留着，才能认出 ```sql 围栏。
            stripped = data.lstrip(" \t\r\n")
            if not stripped:
                self._carry = data
                break
            lower = stripped.lower()
            # 逐行注释：完整出现 SELECT 或 WITH，后面整段都不给用户看。
            if any(lower.startswith(opener) for opener in _SQL_OPENERS):
                self._dropping = True
                emitted.append(self._drop_until_chinese(stripped))
                break
            # 逐行注释：片段还可能是 SELECT 的前缀，例如只来了 "SEL"。
            if any(opener.startswith(lower) for opener in _SQL_OPENERS) and "\n" not in stripped:
                self._carry = data
                break
            emitted.append(data)
            break
        return "".join(emitted)

    def _drop_until_chinese(self, data: str) -> str:
        """丢掉 SQL，从第一个汉字开始恢复展示。"""
        # 逐行注释：汉字一出现，说明教练开始说话了。
        match = re.search(r"[\u4e00-\u9fff]", data)
        if match is None:
            return ""
        self._dropping = False
        # 逐行注释：汉字后面仍走一遍过滤，防止同一段里还有第二条 SQL。
        return self.feed(data[match.start() :])

    def flush(self) -> str:
        """流结束时交出仍在缓冲里、且不是 SQL 的文字。"""
        # 逐行注释：正在丢弃 SQL 时，缓冲里剩下的也是 SQL。
        if self._dropping:
            self._carry = ""
            self._dropping = False
            return ""
        text = self._carry
        self._carry = ""
        sample = text.lstrip().lower()
        # 逐行注释：没收完的 SELECT 前缀不展示。
        if sample and any(opener.startswith(sample) or sample.startswith(opener) for opener in _SQL_OPENERS):
            return ""
        return text


def _is_live_coach_token(chunk: Any) -> bool:
    """只收下模型正在生成的新字。历史消息是完整消息，不能再念一遍。"""
    # 逐行注释：流式新字的类型名是 AIMessageChunk。
    # 逐行注释：记忆里的旧问题和旧回答是 HumanMessage、AIMessage，类型名对不上。
    return type(chunk).__name__ == "AIMessageChunk"


def ask_agent_stream(agent: Any, user_text: str, thread_id: str = DEFAULT_THREAD_ID) -> Iterator[str]:
    """流式调用 Agent，仅产出可展示的 AI 文本片段（过滤工具消息）。"""
    # 逐行注释：需要数字时追加强制调工具提示，避免空口承诺。
    input_payload = _turn_input(_with_tool_nudge(user_text))
    # 逐行注释：累积已看到的文本，用于识别重复和英文摘要。
    spoken = ""
    # 逐行注释：标题可能被拆成多个片段，先暂存，确认不是摘要后再送出。
    held = ""
    # 逐行注释：已经主动截断时，缓冲区里剩下的是不该打印的内容。
    stopped = False
    # 逐行注释：一轮里只要开始查游泳数据，等待语只说一次。
    said_wait = False
    # 逐行注释：工具名可能被拆成几次流式片段，先拼起来再判断。
    pending_tool_name = ""
    # 逐行注释：子代理的 SQL 即使漏进正文，也不往外送。
    sql_filter = _SqlLeakFilter()
    # 逐行注释：被丢掉的旧消息条数，用来确认没有把历史又念一遍。
    skipped_old = 0
    # 逐行注释：这一轮实际点过的工具名，重复的不记第二次。
    tool_names: list[str] = []
    # 逐行注释：和接口共用一个日志器，工具调用写在同一份 coach.log 里。
    logger = logging.getLogger("swim_coach")
    for event in agent.stream(input_payload, _thread_config(thread_id), stream_mode="messages"):
        # create_agent 的 stream_mode=messages 常见返回：(chunk, metadata)。
        if isinstance(event, tuple) and event:
            chunk = event[0]
        else:
            chunk = event
        # 逐行注释：跳过工具返回消息，避免把 JSON 结果打印给用户。
        if _is_tool_message(chunk):
            continue
        # 逐行注释：旧对话会整段出现在流里，那些不是新生成的字，丢掉。
        if not _is_live_coach_token(chunk):
            # 逐行注释：只计数，不把旧内容写进日志。
            skipped_old += 1
            continue
        # 逐行注释：只有点名查游泳数据库时才出等待语。档案、参考卡和问候都不说这句。
        tool_chunks = getattr(chunk, "tool_call_chunks", None) or []
        if not said_wait:
            for item in tool_chunks:
                # 逐行注释：片段里有名字就接上，空名字是后续参数，跳过。
                tool_name = item.get("name") if isinstance(item, dict) else getattr(item, "name", "") or ""
                if not tool_name:
                    continue
                pending_tool_name += tool_name
                if _QUERY_TOOL in pending_tool_name:
                    said_wait = True
                    # 逐行注释：查库开始的时刻写进日志，设备上的等待语应对得上这一行。
                    logger.info("tool %s thread=%s", _QUERY_TOOL, thread_id)
                    yield COACH_WAIT_LINE
                    break
                # 逐行注释：其他工具也记下名字，看长句有没有乱调用。
                if pending_tool_name and pending_tool_name not in tool_names:
                    tool_names.append(pending_tool_name)
                    logger.info("tool %s thread=%s", pending_tool_name, thread_id)
        content = getattr(chunk, "content", "")
        text = sql_filter.feed(_normalize_chunk_text(content))
        if not text:
            continue
        # 逐行注释：先拼进缓冲区再判断，重复段和英文摘要不再继续往外送。
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
        # 逐行注释：仍像摘要标题开头时先不打印，避免 "## SESSION" 漏出去。
        if _is_summary_heading_prefix(held):
            continue
        yield held
        held = ""
    # 逐行注释：正常结束时把最后暂存的几个字送出。
    if not stopped:
        tail = sql_filter.flush()
        if tail:
            held += tail
    if held and not stopped:
        yield held
    # 逐行注释：这一轮模型侧结束。跳过的旧消息多，说明记忆还在，但没有再念出来。
    logger.info(
        "model done thread=%s skipped_old=%d tools=%s stopped=%s",
        thread_id,
        skipped_old,
        ",".join(tool_names) if tool_names else "-",
        stopped,
    )

