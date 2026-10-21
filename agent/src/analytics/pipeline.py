# 模块级说明：将 CSV 解析、派生指标计算、evidence 落库串为可重跑的分析流水线。

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.analytics.metrics import build_evidence_from_csv
from src.ingest.csv_parser import parse_activity_from_csv, parse_cn_number, parse_time_to_seconds
from src.repository.swim_repo import SwimRepository


def run_activity_analytics(
    repo: SwimRepository,
    csv_path: Path,
    activity_id: str | None = None,
) -> dict[str, Any]:
    """对 CSV 活动执行 P0 分析并写库。"""
    parsed = parse_activity_from_csv(csv_path)
    if activity_id is not None and parsed.activity_id != activity_id:
        raise ValueError(f"activity_id mismatch: expected {activity_id}, got {parsed.activity_id}")

    lengths_payload: list[dict[str, Any]] = []
    index = 0
    for row in parsed.child_rows:
        elapsed = parse_time_to_seconds(row.get("时间"))
        lengths_payload.append(
            {
                "length_index": index,
                "length_type": "active",
                "swim_stroke": row.get("泳姿"),
                "total_strokes": parse_cn_number(row.get("总划水次数")),
                "avg_speed_mps": None,
                "avg_swimming_cadence": parse_cn_number(row.get("平均划频")),
                "total_elapsed_s": elapsed,
                "total_timer_s": elapsed,
                "is_active": 1,
            }
        )
        index += 1

    for row in parsed.rest_rows:
        elapsed = parse_time_to_seconds(row.get("时间"))
        lengths_payload.append(
            {
                "length_index": index,
                "length_type": "idle",
                "swim_stroke": row.get("泳姿"),
                "total_strokes": parse_cn_number(row.get("总划水次数")),
                "avg_speed_mps": None,
                "avg_swimming_cadence": parse_cn_number(row.get("平均划频")),
                "total_elapsed_s": elapsed,
                "total_timer_s": elapsed,
                "is_active": 0,
            }
        )
        index += 1
    repo.replace_lengths(parsed.activity_id, lengths_payload)

    evidence = build_evidence_from_csv(
        activity_id=parsed.activity_id,
        summary_metrics=parsed.summary_metrics,
        child_rows=parsed.child_rows,
        rest_rows=parsed.rest_rows,
    )

    repo.replace_laps_enriched(
        parsed.activity_id,
        [
            {
                "lap_index": lap["lap_index"],
                "distance_m": lap["distance_m"],
                "elapsed_s": lap["elapsed_s"],
                "timer_s": lap["elapsed_s"],
                "pace_per_100m_s": lap["pace_per_100m_s"],
                "avg_hr": lap["avg_hr"],
                "max_hr": lap["max_hr"],
                "total_strokes": lap["total_strokes"],
                "swim_stroke_hint": lap.get("stroke"),
                "swolf_derived": lap["swolf_derived"],
                "is_rest_lap": 0,
            }
            for lap in evidence["laps"]
        ],
    )

    repo.upsert_evidence(parsed.activity_id, evidence)
    repo.upsert_performance_state(
        athlete_id="default",
        state={
            "latest_activity_id": parsed.activity_id,
            "latest_labels": evidence["l2"]["labels"],
            "last_avg_hr": evidence["l0"]["avg_hr"],
            "last_total_distance_m": evidence["l0"]["total_distance_m"],
            "last_avg_swolf_derived": evidence["l1"]["avg_swolf_derived"],
        },
    )
    return evidence
