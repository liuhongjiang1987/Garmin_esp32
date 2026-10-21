"""把一场 FIT 游泳收成教练证据和可落库的每一趟。

整场配速、SWOLF 用 swim_metrics 里已和 CSV 对过的算法。
开始时间由调用方传入，使用活动库里的本地时间，不用 FIT 里的 UTC。
"""

from __future__ import annotations

from typing import Any

from swimcore.fit_activity import FitSwimActivity
from swimcore.metrics import active_lengths, rest_ratio, rest_time_s, session_avg_pace_s, session_avg_swolf, session_best_pace_s


def build_fit_evidence(activity: FitSwimActivity, start_time: str) -> dict[str, Any]:
    """生成与 CSV 证据相同层级的 evidence。单趟心率 FIT 的 length 里没有，留空。"""
    swimming = active_lengths(activity.lengths)
    paces = [lap.pace_per_100m_s for lap in swimming if lap.pace_per_100m_s is not None]
    resting = rest_time_s(activity.lengths)
    active_time = sum(lap.elapsed_s for lap in swimming)
    return {
        "activity_id": activity.activity_id,
        "start_time": start_time,
        "source": "fit_length",
        "l0": {
            "total_distance_m": activity.total_distance_m,
            "total_elapsed_s": round(activity.total_timer_s),
            "total_timer_s": activity.total_timer_s,
            "total_strokes": activity.total_strokes,
            "avg_hr": activity.avg_hr,
            "max_hr": activity.max_hr,
            "pool_length": activity.pool_length_m,
            "pool_length_unit": "metric",
            "num_laps": len(swimming),
            "num_lengths": len(activity.lengths),
        },
        "l1": {
            "active_lap_count": len(swimming),
            "rest_lap_count": sum(1 for lap in activity.lengths if lap.is_rest),
            "active_time_s": active_time,
            "rest_time_s": resting,
            "rest_time_ratio": rest_ratio(activity.lengths),
            "best_pace_per_100m_s": session_best_pace_s(activity.lengths),
            "worst_pace_per_100m_s": max(paces) if paces else None,
            "avg_pace_per_100m_s": session_avg_pace_s(activity.lengths, activity.total_distance_m),
            "avg_swolf_derived": session_avg_swolf(activity.lengths),
            "active_length_count": len(swimming),
        },
        "l2": {"labels": []},
        "laps": [
            {
                "lap_index": lap.lap_index,
                "stroke": lap.stroke,
                "distance_m": lap.distance_m,
                "elapsed_s": lap.elapsed_s,
                "pace_per_100m_s": lap.pace_per_100m_s,
                "total_strokes": lap.total_strokes,
                "swolf_derived": lap.swolf,
                "avg_hr": None,
                "max_hr": None,
                "is_rest_lap": False,
            }
            for lap in swimming
        ],
    }


def length_rows(activity: FitSwimActivity) -> list[dict[str, Any]]:
    """按 FIT 原始顺序写出每一趟，含休息。"""
    rows: list[dict[str, Any]] = []
    for index, lap in enumerate(activity.lengths):
        rows.append(
            {
                "length_index": index,
                "length_type": "idle" if lap.is_rest else "active",
                "swim_stroke": lap.stroke,
                "total_strokes": lap.total_strokes,
                "avg_speed_mps": None,
                "avg_swimming_cadence": None,
                "total_elapsed_s": lap.elapsed_s,
                "total_timer_s": lap.elapsed_s,
                "is_active": 0 if lap.is_rest else 1,
            }
        )
    return rows


def enriched_lap_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """只写游泳趟，供 SQL 按泳姿切前后半。"""
    return [
        {
            "lap_index": lap["lap_index"],
            "distance_m": lap["distance_m"],
            "elapsed_s": lap["elapsed_s"],
            "timer_s": lap["elapsed_s"],
            "pace_per_100m_s": lap["pace_per_100m_s"],
            "avg_hr": None,
            "max_hr": None,
            "total_strokes": lap["total_strokes"],
            "swim_stroke_hint": lap["stroke"],
            "swolf_derived": lap["swolf_derived"],
            "is_rest_lap": 0,
        }
        for lap in evidence["laps"]
    ]
