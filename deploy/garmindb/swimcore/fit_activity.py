"""从泳池游泳 FIT 读取每一趟。

GarminDB 的 activity_laps 是间歇，一圈里可能含多趟，不能用来对 CSV 的子圈。
每一趟在 FIT 的 length 消息里：length_type 为 active 是游泳，idle 是休息。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitdecode

from swimcore.metrics import SwimLength, make_length


# FIT 泳姿名到教练口径的中文。混合泳只出现在间歇上，不会出现在单趟里。
_STROKE_ZH = {
    "freestyle": "自由泳",
    "breaststroke": "蛙泳",
    "backstroke": "仰泳",
    "butterfly": "蝶泳",
    "drill": "练习",
    "mixed": "混合泳",
}


@dataclass
class FitSwimActivity:
    """一场泳池游泳的原始摘要和每一趟。"""

    activity_id: str
    pool_length_m: float
    total_distance_m: float
    total_timer_s: float
    total_strokes: int | None
    avg_hr: int | None
    max_hr: int | None
    lengths: list[SwimLength]


def _enum_name(value) -> str | None:
    """把 fitdecode 的枚举收成小写名字，例如 freestyle、active。"""
    if value is None:
        return None
    text = getattr(value, "name", None) or str(value)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()


def _first_values(frame) -> dict:
    """同一字段出现多次时保留第一个非空值。FIT 里速度字段会再写一次空值。"""
    values: dict = {}
    for field in frame.fields:
        if field.name in values and values[field.name] is not None:
            continue
        values[field.name] = field.value
    return values


def _pool_length_m(session: dict) -> float:
    """池长转成米。英制池长按码换算。"""
    length = float(session.get("pool_length") or 0.0)
    unit = _enum_name(session.get("pool_length_unit"))
    if unit == "statute":
        return length * 0.9144
    return length


def read_swim_fit(fit_path: Path, activity_id: str | None = None) -> FitSwimActivity:
    """读取一场活动 FIT，得到摘要和按时间排列的每一趟。"""
    session = None
    length_messages: list[dict] = []
    with fitdecode.FitReader(str(fit_path)) as reader:
        for frame in reader:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "session":
                session = _first_values(frame)
            elif frame.name == "length":
                length_messages.append(_first_values(frame))
    if session is None:
        raise ValueError(f"{fit_path} 没有 session 记录")
    pool_length_m = _pool_length_m(session)
    if pool_length_m <= 0:
        raise ValueError(f"{fit_path} 没有池长")

    lengths: list[SwimLength] = []
    active_index = 0
    for message in length_messages:
        kind = _enum_name(message.get("length_type"))
        is_rest = kind != "active"
        elapsed_s = float(message.get("total_timer_time") or 0.0)
        strokes = message.get("total_strokes")
        strokes_i = None if strokes is None else int(strokes)
        stroke_name = "休息" if is_rest else _STROKE_ZH.get(_enum_name(message.get("swim_stroke")) or "", "未知")
        lap_index = active_index if not is_rest else -1
        if not is_rest:
            active_index += 1
        lengths.append(
            make_length(
                lap_index=lap_index,
                stroke=stroke_name,
                distance_m=pool_length_m,
                elapsed_s=elapsed_s,
                total_strokes=strokes_i,
                is_rest=is_rest,
            )
        )

    resolved_id = activity_id or fit_path.name.split("_", 1)[0]
    total_strokes = session.get("total_strokes")
    return FitSwimActivity(
        activity_id=resolved_id,
        pool_length_m=pool_length_m,
        total_distance_m=float(session.get("total_distance") or 0.0),
        total_timer_s=float(session.get("total_timer_time") or 0.0),
        total_strokes=None if total_strokes is None else int(total_strokes),
        avg_hr=session.get("avg_heart_rate"),
        max_hr=session.get("max_heart_rate"),
        lengths=lengths,
    )
