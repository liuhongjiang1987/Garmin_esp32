"""内网接口。设备把识别出的问句发来，取回教练原文，并按原文合成语音。"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from collections.abc import Iterator

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from src.coach_agent import (
    COACH_WAIT_LINE,
    ask_agent_stream,
    bind_query_notifier,
    create_coach_agent,
    reset_query_notifier,
)
from src.config import load_settings
from src.repository.swim_repo import DbPaths, SwimRepository
from src.speech import cached_wav, remember_wav, synthesize_wav, warm_phrase
from src.tools import build_tools


_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _logger() -> logging.Logger:
    """教练运行日志写到标准输出，也写到 /data/coach.log，方便对照每次测试。"""
    # 逐行注释：同名日志器只初始化一次，避免每次请求重复加处理器。
    logger = logging.getLogger("swim_coach")
    if logger.handlers:
        return logger
    # 逐行注释：信息级就够用，不把模型请求体里的密钥打出来。
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # 逐行注释：时间、级别、内容，一行一件事。
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    # 逐行注释：容器标准输出，docker logs 能直接看到。
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    # 逐行注释：默认落到数据盘，群晖共享里可以直接打开。
    path = os.getenv("COACH_LOG_PATH", "/data/logs/coach.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file = logging.FileHandler(path, encoding="utf-8")
        file.setFormatter(formatter)
        logger.addHandler(file)
    except OSError:
        # 逐行注释：目录不可写时仍保留标准输出，不让接口起不来。
        logger.warning("coach log file unavailable: %s", path)
    return logger


def _preview(text: str, limit: int = 80) -> str:
    """日志里只留开头一小段，避免一整段长语音把文件撑满。"""
    # 逐行注释：换行压成空格，保证一条日志占一行。
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "…"
_WAIT_PREFIXES = (
    COACH_WAIT_LINE.strip(),
    "好的，请稍等，我先看看您的训练数据。",
    "好的，请稍等。",
)


_SENTENCE_END = "。！？\n"
_SENTENCE_SOFT = "，、；："
_GREETING_LINE = "你好，我在。想了解训练，直接问我就行。"
_UNFOCUSED_LINE = "你想查的话，直接说最近一场的配速，或者点一个主题就行。"
_QUERY_CUES = (
    "配速",
    "swolf",
    "SWOLF",
    "划水",
    "划次",
    "距离",
    "自由泳",
    "蛙泳",
    "仰泳",
    "蝶泳",
    "混合泳",
    "多少",
    "几次",
    "后程",
    "前程",
    "趋势",
    "耐力",
    "效率",
    "稳定",
    "负荷",
    "对比",
    "数据",
    "记录",
)


def _take_sentences(buffer: str) -> tuple[list[str], str]:
    """从已经流出来的文字里切出可以先念的句子，剩下的继续攒。"""
    # 逐行注释：句号一到就切。没有句号时，满四十字左右也在逗号处切开，好让第一句早点出声。
    sentences: list[str] = []
    start = 0
    index = 0
    while index < len(buffer):
        char = buffer[index]
        cut = char in _SENTENCE_END or (index - start >= 40 and char in _SENTENCE_SOFT)
        if cut:
            piece = buffer[start : index + 1].strip()
            start = index + 1
            if piece:
                sentences.append(piece)
        index += 1
    return sentences, buffer[start:]


def _quick_reply(text: str) -> str | None:
    """长段里没有可查的项目时，不启动教练，直接回一句。"""
    # 逐行注释：去掉空白后数字符，短句仍然走完整教练。
    compact = "".join(text.split())
    # 逐行注释：不到二十个字，就算没点名，也留给教练用一句话问清楚。
    if len(compact) < 20:
        return None
    # 逐行注释：点了配速、距离或主题，就必须查库，不能在这里截断。
    lowered = compact.lower()
    if any(cue.lower() in lowered for cue in _QUERY_CUES):
        return None
    # 逐行注释：固定一句，和设备本地的说法一致，方便语音缓存命中。
    return _UNFOCUSED_LINE


def _strip_wait_line(reply: str) -> str:
    """去掉开头的等待语。这句话只在查到数据时由设备单独播出。"""
    text = reply.strip()
    changed = True
    while changed and text:
        changed = False
        for prefix in _WAIT_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
                break
    return text


class AskRequest(BaseModel):
    """一次提问。session_id 相同则沿用这一路对话。"""

    text: str = Field(min_length=1, max_length=2000)
    session_id: str = "device"


def create_app() -> FastAPI:
    """启动时建好教练，之后每次请求只传入问句。"""
    # 逐行注释：读取模型、证据库和教练库路径。
    settings = load_settings()
    # 逐行注释：已有库也补齐新表，避免 CSS 工具碰到 no such table。
    from src.db.schema import init_coach_db

    init_coach_db(settings.coach_db_path)
    # 逐行注释：档案仍在本机 coach.db，训练数字在 NAS 的 swim_evidence.db。
    repo = SwimRepository(
        DbPaths(
            coach_db=settings.coach_db_path,
            garmin_db=settings.garmin_db_path,
            garmin_activities_db=settings.garmin_activities_db_path,
        )
    )
    # 逐行注释：和命令行共用同一个教练，避免接口另写一套提示词。
    agent = create_coach_agent(settings=settings, tools=build_tools(repo), repo=repo)
    # 逐行注释：等待语固定不变，启动时先合成好，用户一问就能马上听到。
    warm_phrase(COACH_WAIT_LINE.strip(), api_key=settings.model_api_key, base_url=settings.model_base_url)
    # 逐行注释：问候语每次都一样，启动时合成好，设备来取就不用再等上游。
    warm_phrase(_GREETING_LINE, api_key=settings.model_api_key, base_url=settings.model_base_url)
    # 逐行注释：没有明确查询时的那句也固定，一并预热。
    warm_phrase(_UNFOCUSED_LINE, api_key=settings.model_api_key, base_url=settings.model_base_url)
    # 逐行注释：没设置口令时只建议绑在本机。设置后请求必须带 Bearer。
    token = os.getenv("COACH_API_TOKEN", "").strip()
    app = FastAPI(title="swim-coach")

    @app.get("/health")
    def health() -> dict[str, bool]:
        """给设备和你自己确认接口已经起来。"""
        return {"ok": True}

    @app.post("/ask")
    def ask(body: AskRequest, authorization: str | None = Header(default=None)) -> StreamingResponse:
        """回答一句问话。开始查游泳数据时先送出等待语，正文结束后再送正式回答。"""
        # 逐行注释：口令不对就拒绝，不把问题送进模型。
        if token and authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="unauthorized")
        # 逐行注释：会话号只允许字母数字，避免任意字符串进入记忆键。
        session_id = body.session_id if _SESSION_ID.fullmatch(body.session_id) else "device"

        def events() -> Iterator[str]:
            # 逐行注释：记下这一轮从什么时候开始，结束时算耗时。
            started = time.monotonic()
            # 逐行注释：问句只留开头，会话号用来把同一台设备的多轮对上。
            _logger().info("ask start session=%s text=%s", session_id, _preview(body.text))
            # 逐行注释：空泛长句不进模型，避免查库把会话拖到断开。
            quick = _quick_reply(body.text)
            if quick:
                # 逐行注释：没进模型也要留下耗时，方便和查库的轮次区分。
                _logger().info("ask quick session=%s ms=%d text=%s", session_id, int((time.monotonic() - started) * 1000), _preview(quick))
                yield json.dumps({"event": "sentence", "text": quick}, ensure_ascii=False) + "\n"
                yield json.dumps({"event": "reply", "text": quick}, ensure_ascii=False) + "\n"
                return
            # 逐行注释：子代理在另一头跑的时候，等待语从这里立刻送出。
            mailbox: queue.Queue = queue.Queue()
            # 逐行注释：模型决定调用和函数真正进入都可能各报一次，只送出一句。
            announced = False

            def on_query() -> None:
                nonlocal announced
                if announced:
                    return
                announced = True
                # 逐行注释：只有真正去查游泳数据才记这一笔。
                _logger().info("ask query session=%s", session_id)
                mailbox.put(("wait", None))

            def run() -> None:
                # 逐行注释：监听必须设在跑教练的这个线程里，子代理才能看见。
                token = bind_query_notifier(on_query)
                try:
                    for piece in ask_agent_stream(agent, body.text.strip(), thread_id=session_id):
                        if piece.strip() == COACH_WAIT_LINE.strip():
                            on_query()
                            continue
                        mailbox.put(("text", piece))
                except Exception:
                    # 逐行注释：失败原因写入日志，返回给设备的仍是一句口语。
                    _logger().exception("ask failed session=%s", session_id)
                    mailbox.put(("text", "教练没有答上来。"))
                finally:
                    reset_query_notifier(token)
                    mailbox.put(("end", None))

            threading.Thread(target=run, name="coach-ask", daemon=True).start()
            parts: list[str] = []
            pending = ""
            while True:
                kind, payload = mailbox.get()
                if kind == "wait":
                    yield json.dumps({"event": "wait"}, ensure_ascii=False) + "\n"
                    continue
                if kind == "end":
                    break
                # 逐行注释：模型还在写后面的句子时，先把已经写完的句子送出去合成。
                pending += payload or ""
                ready, pending = _take_sentences(pending)
                for sentence in ready:
                    sentence = _strip_wait_line(sentence)
                    if not sentence:
                        continue
                    parts.append(sentence)
                    yield json.dumps({"event": "sentence", "text": sentence}, ensure_ascii=False) + "\n"
            tail = _strip_wait_line(pending)
            if tail:
                parts.append(tail)
                yield json.dumps({"event": "sentence", "text": tail}, ensure_ascii=False) + "\n"
            reply = _strip_wait_line("".join(parts))
            # 逐行注释：一轮结束时留下句数、字数和耗时，用来对照设备上的快慢。
            _logger().info(
                "ask done session=%s ms=%d sentences=%d chars=%d text=%s",
                session_id,
                int((time.monotonic() - started) * 1000),
                len(parts),
                len(reply),
                _preview(reply),
            )
            yield json.dumps({"event": "reply", "text": reply}, ensure_ascii=False) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.post("/speak")
    def speak(body: AskRequest, authorization: str | None = Header(default=None)) -> Response:
        """把已经写好的教练原文合成语音，不重新回答。"""
        # 逐行注释：和提问接口共用口令，避免播报口子单独暴露。
        if token and authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="unauthorized")
        # 逐行注释：空句子不送给合成，避免上游报错。
        spoken = body.text.strip()
        if not spoken:
            raise HTTPException(status_code=400, detail="empty")
        # 逐行注释：合成开始时间，用来看是缓存命中还是重新请求。
        started = time.monotonic()
        try:
            # 逐行注释：等待语命中缓存就直接回音频，正式回答整段合成一次。
            wav = cached_wav(spoken)
            cache_hit = wav is not None
            if wav is None:
                wav = synthesize_wav(spoken, api_key=settings.model_api_key, base_url=settings.model_base_url)
                # 逐行注释：短句重复出现，记下来下次直接回，减少合成失败。
                if len(spoken) <= 80:
                    remember_wav(spoken, wav)
            # 逐行注释：记下这句有没有重新合成，以及花了多久。
            _logger().info(
                "speak done cache=%s ms=%d bytes=%d text=%s",
                cache_hit,
                int((time.monotonic() - started) * 1000),
                len(wav),
                _preview(spoken),
            )
        except Exception as exc:
            # 逐行注释：合成失败只记原因，不把密钥写进日志。
            _logger().error("speak failed text=%s error=%s", _preview(spoken), str(exc)[:200])
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(content=wav, media_type="audio/wav")

    # 逐行注释：启动时就打开日志文件，确认这次容器用的是新代码。
    _logger().info("coach api ready")
    return app
