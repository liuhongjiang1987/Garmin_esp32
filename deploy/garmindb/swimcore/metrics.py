"""由每一趟的用时、距离和划次计算配速与 SWOLF。

整场平均配速不用各趟配速再平均，而是用游泳用时合计除以总距离。
整场 SWOLF 是各趟（用时加划次）的平均值，再四舍五入。
这两条与 Garmin 导出的 CSV 摘要一致。配速单位是秒/100 米，数值越小越快。
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass
class SwimLength:
    """一趟游泳或一段休息。休息趟距离为 0，不参与配速和 SWOLF。"""

    lap_index: int
    stroke: str
    distance_m: float
    elapsed_s: float
    total_strokes: int | None
    pace_per_100m_s: float | None
    swolf: float | None
    is_rest: bool


def pace_per_100m(elapsed_s: float, distance_m: float) -> float | None:
    """用这一趟的用时和距离计算秒/100 米。"""
    if distance_m <= 0:
        return None
    return (elapsed_s / distance_m) * 100.0


def length_swolf(elapsed_s: float, total_strokes: int | None) -> float | None:
    """SWOLF 是这一趟用时（秒）加上划次。"""
    if total_strokes is None:
        return None
    return elapsed_s + total_strokes


def make_length(
    lap_index: int,
    stroke: str,
    distance_m: float,
    elapsed_s: float,
    total_strokes: int | None,
    is_rest: bool,
) -> SwimLength:
    """组装一趟，并写上配速和 SWOLF。"""
    pace = None if is_rest else pace_per_100m(elapsed_s, distance_m)
    swolf = None if is_rest else length_swolf(elapsed_s, total_strokes)
    return SwimLength(
        lap_index=lap_index,
        stroke=stroke,
        distance_m=0.0 if is_rest else distance_m,
        elapsed_s=elapsed_s,
        total_strokes=0 if is_rest else total_strokes,
        pace_per_100m_s=pace,
        swolf=swolf,
        is_rest=is_rest,
    )


def active_lengths(lengths: list[SwimLength]) -> list[SwimLength]:
    """只留真正在游的趟，顺序与原列表一致。"""
    return [lap for lap in lengths if not lap.is_rest]


def session_avg_pace_s(lengths: list[SwimLength], total_distance_m: float) -> int | None:
    """整场平均配速：各趟游泳用时之和 / 总距离 × 100，再四舍五入到秒。"""
    swimming = active_lengths(lengths)
    if total_distance_m <= 0 or not swimming:
        return None
    active_time_s = sum(lap.elapsed_s for lap in swimming)
    return round(active_time_s / total_distance_m * 100.0)


def session_avg_swolf(lengths: list[SwimLength]) -> int | None:
    """整场 SWOLF：各趟 SWOLF 的平均值，四舍五入到整数。"""
    values = [lap.swolf for lap in active_lengths(lengths) if lap.swolf is not None]
    if not values:
        return None
    return round(mean(values))


def session_best_pace_s(lengths: list[SwimLength]) -> int | None:
    """最快的一趟配速，四舍五入到秒。"""
    values = [lap.pace_per_100m_s for lap in active_lengths(lengths) if lap.pace_per_100m_s is not None]
    if not values:
        return None
    return round(min(values))


def rest_time_s(lengths: list[SwimLength]) -> float:
    """休息用时合计。"""
    return sum(lap.elapsed_s for lap in lengths if lap.is_rest)


def rest_ratio(lengths: list[SwimLength]) -> float | None:
    """休息用时占游泳加休息的比例。"""
    swimming = sum(lap.elapsed_s for lap in active_lengths(lengths))
    resting = rest_time_s(lengths)
    total = swimming + resting
    if total <= 0:
        return None
    return resting / total


def stroke_halves(lengths: list[SwimLength], stroke: str) -> tuple[list[SwimLength], list[SwimLength]]:
    """按出场顺序把某一泳姿分成前后两半。前半是前 total//2 趟。"""
    chosen = [lap for lap in active_lengths(lengths) if lap.stroke == stroke]
    half = len(chosen) // 2
    return chosen[:half], chosen[half:]
