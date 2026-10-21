# 模块级说明：基于 CSV 子圈/休息/摘要行计算游泳指标、标签与证据包。

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from src.ingest.csv_parser import parse_cn_number, parse_time_to_seconds


@dataclass
class CsvLapDerived:
    """单个子圈派生值。"""

    lap_index: int
    interval_id: str
    stroke: str
    distance_m: float
    elapsed_s: float
    pace_per_100m_s: float | None
    swolf: float | None
    avg_hr: int | None
    max_hr: int | None
    total_strokes: int | None


def compute_child_lap_derived(child_rows: list[dict[str, Any]]) -> list[CsvLapDerived]:
    """从 CSV 子圈行计算每圈派生值。"""
    result: list[CsvLapDerived] = []
    for idx, row in enumerate(child_rows):
        distance_m = float(parse_cn_number(row.get("距离")) or 0.0)
        elapsed_s = float(parse_time_to_seconds(row.get("时间")) or 0.0)
        pace = parse_time_to_seconds(row.get("平均配速"))
        if pace is None and distance_m > 0:
            pace = (elapsed_s / distance_m) * 100.0
        total_strokes = parse_cn_number(row.get("总划水次数"))
        total_strokes_i = int(total_strokes) if total_strokes is not None else None
        swolf = parse_cn_number(row.get("平均 Swolf"))
        if swolf is None and total_strokes_i is not None:
            swolf = elapsed_s + total_strokes_i
        result.append(
            CsvLapDerived(
                lap_index=idx,
                interval_id=(row.get("间歇训练") or "").strip(),
                stroke=(row.get("泳姿") or "").strip(),
                distance_m=distance_m,
                elapsed_s=elapsed_s,
                pace_per_100m_s=pace,
                swolf=swolf,
                avg_hr=int(parse_cn_number(row.get("平均心率")) or 0) or None,
                max_hr=int(parse_cn_number(row.get("最大心率")) or 0) or None,
                total_strokes=total_strokes_i,
            )
        )
    return result


def detect_labels(derived_laps: list[CsvLapDerived], rest_rows: list[dict[str, Any]]) -> list[str]:
    """基于规则生成 L2 标签。"""
    labels: list[str] = []
    active = [lap for lap in derived_laps if lap.pace_per_100m_s is not None]
    rest_hrs = [parse_cn_number(row.get("平均心率")) for row in rest_rows]
    rest = [x for x in rest_hrs if x is not None]
    if len(active) >= 4:
        half = len(active) // 2
        first_half = [lap.pace_per_100m_s for lap in active[:half] if lap.pace_per_100m_s]
        second_half = [lap.pace_per_100m_s for lap in active[half:] if lap.pace_per_100m_s]
        if first_half and second_half and mean(second_half) > mean(first_half) * 1.12:
            labels.append("late_fade")
    if rest:
        if mean(float(x) for x in rest) > 145:
            labels.append("rest_incomplete")
    swolf_values = [lap.swolf for lap in active if lap.swolf is not None]
    if swolf_values and max(swolf_values) > min(swolf_values) * 1.35:
        labels.append("efficiency_drop")
    pace_values = [lap.pace_per_100m_s for lap in active if lap.pace_per_100m_s is not None]
    if pace_values and (max(pace_values) - min(pace_values)) > 60:
        labels.append("suspect_length")
    return labels


def build_evidence_from_csv(
    activity_id: str,
    summary_metrics: dict[str, Any] | None,
    child_rows: list[dict[str, Any]],
    rest_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """构建 CSV 主源 evidence pack。"""
    derived = compute_child_lap_derived(child_rows)
    labels = detect_labels(derived, rest_rows)
    active_count = len(derived)
    total_distance_children = sum(lap.distance_m for lap in derived)
    total_time_children = sum(lap.elapsed_s for lap in derived)
    total_strokes_children = sum((lap.total_strokes or 0) for lap in derived)
    # 从子圈数据推断池长（多数值），避免依赖 FIT 的 pool_length
    distances = [lap.distance_m for lap in derived if lap.distance_m > 0]
    pool_length = None
    if distances:
        freq: dict[float, int] = {}
        for d in distances:
            freq[d] = freq.get(d, 0) + 1
        pool_length = max(freq.items(), key=lambda x: x[1])[0]

    best_pace_children = min([lap.pace_per_100m_s for lap in derived if lap.pace_per_100m_s is not None], default=None)
    worst_pace_children = max([lap.pace_per_100m_s for lap in derived if lap.pace_per_100m_s is not None], default=None)
    avg_pace_children = (total_time_children / total_distance_children * 100.0) if total_distance_children > 0 else None
    avg_swolf_children = mean([lap.swolf for lap in derived if lap.swolf is not None]) if derived else None
    rest_times = [float(parse_time_to_seconds(row.get("时间")) or 0.0) for row in rest_rows]
    rest_total_time_s = sum(rest_times)
    rest_avg_time_s = mean(rest_times) if rest_times else None
    rest_hr_values = [parse_cn_number(row.get("平均心率")) for row in rest_rows]
    rest_avg_hr = mean([x for x in rest_hr_values if x is not None]) if rest_hr_values else None

    # 主口径优先使用摘要（包含休息），游动段重算用于技术剖面与口径对账。
    l0_total_distance = summary_metrics.get("total_distance_m") if summary_metrics else total_distance_children
    l0_total_time = summary_metrics.get("total_time_s") if summary_metrics else total_time_children
    l0_total_strokes = summary_metrics.get("total_strokes") if summary_metrics else total_strokes_children
    l0_avg_hr = summary_metrics.get("avg_hr") if summary_metrics else mean(
        [lap.avg_hr for lap in derived if lap.avg_hr is not None]
    ) if derived else None
    l0_max_hr = summary_metrics.get("max_hr") if summary_metrics else max(
        [lap.max_hr for lap in derived if lap.max_hr is not None], default=None
    )

    l1_avg_pace = summary_metrics.get("avg_pace_per_100m_s") if summary_metrics else avg_pace_children
    l1_best_pace = summary_metrics.get("best_pace_per_100m_s") if summary_metrics else best_pace_children
    l1_avg_swolf = summary_metrics.get("avg_swolf") if summary_metrics else avg_swolf_children
    swim_time_ratio = (total_time_children / l0_total_time) if l0_total_time and l0_total_time > 0 else None
    rest_time_ratio = (rest_total_time_s / l0_total_time) if l0_total_time and l0_total_time > 0 else None

    consistency = {
        "distance_delta_m": (l0_total_distance - total_distance_children) if l0_total_distance is not None else None,
        "active_vs_whole_time_delta_s": (total_time_children - l0_total_time) if l0_total_time is not None else None,
        "whole_vs_active_time_delta_s": (l0_total_time - total_time_children) if l0_total_time is not None else None,
        "rest_time_s_from_rows": rest_total_time_s,
        "strokes_delta": (l0_total_strokes - total_strokes_children) if l0_total_strokes is not None else None,
        "avg_pace_delta_s": (l1_avg_pace - avg_pace_children) if (l1_avg_pace is not None and avg_pace_children is not None) else None,
        "avg_swolf_delta": (l1_avg_swolf - avg_swolf_children) if (l1_avg_swolf is not None and avg_swolf_children is not None) else None,
    }

    evidence = {
        "activity_id": activity_id,
        "l0": {
            "total_distance_m": l0_total_distance,
            "total_elapsed_s": l0_total_time,
            "total_timer_s": l0_total_time,
            "total_strokes": l0_total_strokes,
            "avg_hr": l0_avg_hr,
            "max_hr": l0_max_hr,
            "pool_length": pool_length,
            "pool_length_unit": "metric",
            "num_laps": active_count,
            "num_lengths": active_count + len(rest_rows),
        },
        "l1": {
            "active_lap_count": active_count,
            "rest_lap_count": len(rest_rows),
            "active_time_s": total_time_children,
            "rest_time_s": rest_total_time_s,
            "rest_avg_duration_s": rest_avg_time_s,
            "rest_avg_hr": rest_avg_hr,
            "swim_time_ratio": swim_time_ratio,
            "rest_time_ratio": rest_time_ratio,
            "best_pace_per_100m_s": l1_best_pace,
            "worst_pace_per_100m_s": worst_pace_children,
            "avg_pace_per_100m_s": l1_avg_pace,
            "avg_swolf_derived": l1_avg_swolf,
            "active_length_count": active_count,
        },
        "l2": {"labels": labels},
        "source_priority": {
            "total_distance_m": "csv_summary" if summary_metrics else "csv_child_rows",
            "total_elapsed_s": "csv_summary" if summary_metrics else "csv_child_rows",
            "avg_swolf": "csv_summary" if summary_metrics and summary_metrics.get("avg_swolf") is not None else "csv_child_rows",
            "avg_pace_per_100m_s": "csv_summary" if summary_metrics and summary_metrics.get("avg_pace_per_100m_s") is not None else "csv_child_rows",
            "active_time_s": "csv_child_rows",
            "rest_time_s": "csv_rest_rows",
        },
        "consistency_check": consistency,
        "laps": [
            {
                "lap_index": lap.lap_index,
                "interval_id": lap.interval_id,
                "stroke": lap.stroke,
                "distance_m": lap.distance_m,
                "elapsed_s": lap.elapsed_s,
                "pace_per_100m_s": lap.pace_per_100m_s,
                "total_strokes": lap.total_strokes,
                "swolf_derived": lap.swolf,
                "avg_hr": lap.avg_hr,
                "max_hr": lap.max_hr,
                "is_rest_lap": False,
            }
            for lap in derived
        ],
    }
    return evidence

