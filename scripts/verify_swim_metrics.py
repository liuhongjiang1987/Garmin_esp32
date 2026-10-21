"""用三场 CSV 样例核对 FIT 算出的配速、SWOLF 和划次。

CSV 子圈是 Garmin 导出的每一趟。FIT 的 length 消息应对上这些子圈。
整场平均配速、SWOLF、距离、划次和心率对摘要行。
"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from src.analytics.metrics import build_evidence_from_csv  # noqa: E402
from src.analytics.swim_metrics import (  # noqa: E402
    active_lengths,
    session_avg_pace_s,
    session_avg_swolf,
    session_best_pace_s,
    stroke_halves,
)
from src.ingest.csv_parser import parse_activity_from_csv  # noqa: E402
from src.ingest.fit_activity import read_swim_fit  # noqa: E402


ACTIVITY_IDS = ("629742595", "635801116", "638297383")
FIT_DIR = Path("/Volumes/home/garmindb/home/HealthData/FitFiles/Activities")


def _avg(laps, field: str) -> float | None:
    values = [getattr(lap, field) for lap in laps if getattr(lap, field) is not None]
    if not values:
        return None
    return mean(values)


def _check_activity(activity_id: str) -> list[str]:
    """返回这场没对上的说明。空列表表示通过。"""
    errors: list[str] = []
    csv_path = ROOT / "data" / f"activity_{activity_id}.csv"
    fit_path = FIT_DIR / f"{activity_id}_ACTIVITY.fit"
    parsed = parse_activity_from_csv(csv_path)
    evidence = build_evidence_from_csv(
        parsed.activity_id,
        parsed.summary_metrics,
        parsed.child_rows,
        parsed.rest_rows,
    )
    fit = read_swim_fit(fit_path, activity_id)
    swimming = active_lengths(fit.lengths)
    csv_laps = evidence["laps"]
    summary = parsed.summary_metrics or {}

    if len(swimming) != len(csv_laps):
        errors.append(f"趟数 FIT {len(swimming)} CSV {len(csv_laps)}")
    for index, (fit_lap, csv_lap) in enumerate(zip(swimming, csv_laps)):
        if fit_lap.stroke != csv_lap["stroke"] or fit_lap.total_strokes != csv_lap["total_strokes"]:
            errors.append(
                f"第 {index} 趟泳姿或划次不一致：FIT {fit_lap.stroke}/{fit_lap.total_strokes} "
                f"CSV {csv_lap['stroke']}/{csv_lap['total_strokes']}"
            )
        if abs(fit_lap.elapsed_s - csv_lap["elapsed_s"]) > 0.15:
            errors.append(
                f"第 {index} 趟用时差 {fit_lap.elapsed_s - csv_lap['elapsed_s']:.3f} 秒"
            )
        csv_pace = csv_lap["pace_per_100m_s"]
        if csv_pace is not None and fit_lap.pace_per_100m_s is not None:
            if abs(round(fit_lap.pace_per_100m_s) - round(csv_pace)) > 1:
                errors.append(
                    f"第 {index} 趟配速 FIT {fit_lap.pace_per_100m_s:.1f} CSV {csv_pace}"
                )

    checks = [
        ("距离", fit.total_distance_m, summary.get("total_distance_m")),
        ("划次", fit.total_strokes, summary.get("total_strokes")),
        ("平均心率", fit.avg_hr, summary.get("avg_hr")),
        ("最大心率", fit.max_hr, summary.get("max_hr")),
        ("平均配速", session_avg_pace_s(fit.lengths, fit.total_distance_m), summary.get("avg_pace_per_100m_s")),
        ("平均 SWOLF", session_avg_swolf(fit.lengths), summary.get("avg_swolf")),
        ("最佳配速", session_best_pace_s(fit.lengths), summary.get("best_pace_per_100m_s")),
    ]
    for name, got, expected in checks:
        if got != expected:
            errors.append(f"{name} FIT {got} CSV {expected}")

    # CSV 配速先四舍五入到秒再平均，和 FIT 原始用时平均允许差 0.6 秒。
    for stroke in sorted({lap.stroke for lap in swimming}):
        fit_first, fit_second = stroke_halves(fit.lengths, stroke)
        csv_chosen = [lap for lap in csv_laps if lap["stroke"] == stroke]
        half = len(csv_chosen) // 2
        csv_halves = (csv_chosen[:half], csv_chosen[half:])
        for label, fit_half, csv_half in (("前半", fit_first, csv_halves[0]), ("后半", fit_second, csv_halves[1])):
            fit_pace = _avg(fit_half, "pace_per_100m_s")
            csv_pace = mean(lap["pace_per_100m_s"] for lap in csv_half) if csv_half else None
            if fit_pace is not None and csv_pace is not None and abs(fit_pace - csv_pace) > 0.6:
                errors.append(f"{stroke}{label}配速 FIT {fit_pace:.1f} CSV {csv_pace:.1f}")
    return errors


def main() -> None:
    if not FIT_DIR.is_dir():
        raise SystemExit(f"找不到 FIT 目录：{FIT_DIR}")
    failed = False
    for activity_id in ACTIVITY_IDS:
        errors = _check_activity(activity_id)
        if errors:
            failed = True
            print(f"{activity_id} 未通过")
            for error in errors:
                print(f"  {error}")
        else:
            print(f"{activity_id} 通过")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
