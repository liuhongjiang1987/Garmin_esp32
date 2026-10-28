"""把教练已经写好的中文原文合成 16 位单声道 WAV。整段一次合成，避免按句拼接造成卡顿。"""

from __future__ import annotations

import json
import os
import struct
import threading
import urllib.error
import urllib.request


_SAMPLE_RATE = 24000
_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
_VOICE = "FunAudioLLM/CosyVoice2-0.5B:claire"


_cache_lock = threading.Lock()
_wav_cache: dict[str, bytes] = {}


def cached_wav(text: str) -> bytes | None:
    """取已经合成过的句子。等待语会预先放进这里，设备一点就有声音。"""
    with _cache_lock:
        return _wav_cache.get(text)


def remember_wav(text: str, wav: bytes) -> None:
    """记下某句的音频，下次直接返回。"""
    with _cache_lock:
        _wav_cache[text] = wav


def warm_phrase(text: str, *, api_key: str, base_url: str) -> None:
    """后台合成固定等待语，不挡住接口启动。"""

    def run() -> None:
        try:
            remember_wav(text, synthesize_wav(text, api_key=api_key, base_url=base_url))
        except Exception:
            return

    threading.Thread(target=run, name="coach-wait-voice", daemon=True).start()


def synthesize_wav(text: str, *, api_key: str, base_url: str) -> bytes:
    """整段原文合成一条连续 WAV。只有特别长时才切开。"""
    spoken = _prepare(text)
    if not spoken:
        raise ValueError("empty text")
    if not api_key or not base_url:
        raise RuntimeError("tts is not configured")

    pcm_parts: list[bytes] = []
    for piece in _split(spoken):
        blob = _request_audio(piece, api_key=api_key, base_url=base_url)
        pcm_parts.append(_pcm_from_audio(blob))
    pcm = b"".join(pcm_parts)
    if len(pcm) < 2:
        raise RuntimeError("tts returned no audio")
    if len(pcm) % 2:
        pcm = pcm[:-1]
    return _wrap_wav(pcm, _SAMPLE_RATE)


def _prepare(text: str) -> str:
    """去掉空白，保留教练原句。合成接口不接受空串。"""
    return "".join(text.split())


def _split(text: str, limit: int = 500) -> list[str]:
    """短回答整段合成。只有超过上限，才在句号处切开，避免每句重新起音。"""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if len(buf) >= limit and ch in "。！？；":
            pieces.append(buf)
            buf = ""
    if buf.strip():
        pieces.append(buf)
    return pieces or [text]


def _request_audio(text: str, *, api_key: str, base_url: str) -> bytes:
    """向现有模型服务要一段 24000Hz WAV。"""
    url = base_url.rstrip("/") + "/audio/speech"
    model = os.getenv("COACH_TTS_MODEL", _MODEL).strip() or _MODEL
    voice = os.getenv("COACH_TTS_VOICE", _VOICE).strip() or _VOICE
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "wav",
        "sample_rate": _SAMPLE_RATE,
        "stream": False,
        "speed": 1.0,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", errors="replace")
        raise RuntimeError(f"tts http {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"tts unreachable: {exc.reason}") from exc
    if not body:
        raise RuntimeError("tts returned an empty body")
    return body


def _pcm_from_audio(blob: bytes) -> bytes:
    """取出 WAV 里的 16 位 PCM。若上游直接给了 PCM，原样使用。"""
    if not blob.startswith(b"RIFF"):
        return blob
    if len(blob) < 44 or blob[8:12] != b"WAVE":
        raise RuntimeError("tts wav header is invalid")
    offset = 12
    sample_rate = 0
    channels = 0
    bits = 0
    while offset + 8 <= len(blob):
        chunk_id = blob[offset : offset + 4]
        size = struct.unpack_from("<I", blob, offset + 4)[0]
        start = offset + 8
        if chunk_id == b"fmt ":
            if size < 16 or start + 16 > len(blob):
                raise RuntimeError("tts wav fmt is incomplete")
            audio_format, channels, sample_rate, _, _, bits = struct.unpack_from("<HHIIHH", blob, start)
            if audio_format != 1 or channels != 1 or bits != 16 or sample_rate != _SAMPLE_RATE:
                raise RuntimeError(
                    f"tts wav is {audio_format}/{channels}ch/{sample_rate}Hz/{bits}bit"
                )
        elif chunk_id == b"data":
            end = min(start + size, len(blob))
            return blob[start:end]
        offset = start + size + (size & 1)
    raise RuntimeError("tts wav has no data")


def _wrap_wav(pcm: bytes, sample_rate: int) -> bytes:
    """给裸 PCM 加上标准 WAV 头。"""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm
