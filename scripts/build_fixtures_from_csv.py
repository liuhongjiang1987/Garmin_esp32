# 模块：以 CSV 为唯一数据源，构建开发用 GarminDB fixture（活动库）与 coach.db evidence。
# 背景：项目已确定使用 Garmin 导出的泳池 CSV 作为数据来源，不再依赖 FIT/TCX。
# 产物：garmin_activities.db 仅保留 activities 表（agent 实际查询的表）；
#       coach.db 落 evidence / swim_lengths / swim_laps_enriched（分析加工结果）。
# 幂等：每次运行从零重建 garmin_activities.db 的 activities 表；coach.db 复用并覆盖 evidence，保留 profile/主观记忆。

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 逐行注释：把 agent 包加入 import 路径，复用解析与分析流水线。
ROOT = Path(__file__).resolve().parents[1]
AGENT_SRC = ROOT / "agent"
sys.path.insert(0, str(AGENT_SRC))

from src.analytics.pipeline import run_activity_analytics  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.db.schema import init_coach_db  # noqa: E402
from src.ingest.csv_parser import parse_activity_from_csv  # noqa: E402
from src.repository.swim_repo import DbPaths, SwimRepository  # noqa: E402

# 逐行注释：全部 CSV 活动按时间升序排列（含模拟开始时间），最后一场即最新一场。
CSV_ACTIVITIES = [
    {"csv": ROOT / "data" / "activity_629742595.csv", "activity_id": "629742595", "start": "2026-07-24 18:30:00"},
    {"csv": ROOT / "data" / "activity_635801116.csv", "activity_id": "635801116", "start": "2026-08-21 18:30:00"},
    {"csv": ROOT / "data" / "activity_638297383.csv", "activity_id": "638297383", "start": "2026-09-11 18:26:10"},
]

# 逐行注释：activities 表 DDL（仅保留 agent 查询用到的列，对齐 GarminDB 字段名）。
ACTIVITIES_DDL = """
CREATE TABLE activities (
    activity_id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    type TEXT,
    laps INTEGER,
    sport TEXT,
    sub_sport TEXT,
    start_time TEXT,
    stop_time TEXT,
    elapsed_time TEXT NOT NULL DEFAULT '00:00:00',
    moving_time TEXT NOT NULL DEFAULT '00:00:00',
    distance REAL,
    cycles REAL,
    avg_hr INTEGER,
    max_hr INTEGER,
    calories INTEGER,
    avg_speed REAL,
    max_speed REAL
);
"""


def _fmt_hms(seconds: float | None) -> str:
    """秒 → HH:MM:SS 文本（对齐 fixture 时长列格式）。"""
    total = max(0, int(round(float(seconds or 0))))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def rebuild_activities_db(activities_db: Path) -> None:
    """从零重建 garmin_activities.db，仅创建 activities 表。"""
    activities_db.parent.mkdir(parents=True, exist_ok=True)
    if activities_db.exists():
        activities_db.unlink()
    with sqlite3.connect(activities_db) as conn:
        conn.executescript(ACTIVITIES_DDL)
        conn.commit()


def insert_activity_row(activities_db: Path, activity_id: str, start: str, summary: dict, parent_laps: int) -> None:
    """把一场活动摘要写入 activities 表。"""
    total_distance_m = float(summary.get("total_distance_m") or 0.0)
    total_time_s = float(summary.get("total_time_s") or 0.0)
    distance_km = round(total_distance_m / 1000.0, 3)
    # 逐行注释：平均速度按总距离/总时长换算 km/h。
    avg_speed_kmph = round((total_distance_m / total_time_s) * 3.6, 4) if total_time_s > 0 else None
    start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    stop_dt = start_dt + timedelta(seconds=total_time_s)
    with sqlite3.connect(activities_db) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO activities (
                activity_id, name, description, type, laps, sport, sub_sport,
                start_time, stop_time, elapsed_time, moving_time, distance, cycles,
                avg_hr, max_hr, calories, avg_speed
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                activity_id,
                "泳池游泳",
                "fixture from csv",
                "csv",
                parent_laps,
                "swimming",
                "lap_swimming",
                start,
                stop_dt.strftime("%Y-%m-%d %H:%M:%S"),
                _fmt_hms(total_time_s),
                _fmt_hms(total_time_s),
                distance_km,
                summary.get("total_strokes"),
                int(summary["avg_hr"]) if summary.get("avg_hr") is not None else None,
                int(summary["max_hr"]) if summary.get("max_hr") is not None else None,
                int(summary["calories"]) if summary.get("calories") is not None else None,
                avg_speed_kmph,
            ),
        )
        conn.commit()


def main() -> None:
    """重建 fixture 活动库并落 evidence。"""
    settings = load_settings()
    # 逐行注释：确保 coach.db schema 存在（复用，不清空用户状态）。
    init_coach_db(settings.coach_db_path)
    # 逐行注释：从零重建活动库（仅 activities 表）。
    rebuild_activities_db(settings.garmin_activities_db_path)

    repo = SwimRepository(
        DbPaths(
            coach_db=settings.coach_db_path,
            garmin_db=settings.garmin_db_path,
            garmin_activities_db=settings.garmin_activities_db_path,
        )
    )
    for item in CSV_ACTIVITIES:
        csv_path: Path = item["csv"]
        activity_id: str = item["activity_id"]
        if not csv_path.exists():
            print(f"[skip] 缺少 CSV: {csv_path}")
            continue
        parsed = parse_activity_from_csv(csv_path)
        summary = parsed.summary_metrics or {}
        parent_laps = len(parsed.parent_rows)
        insert_activity_row(settings.garmin_activities_db_path, activity_id, item["start"], summary, parent_laps)
        evidence = run_activity_analytics(repo, csv_path, activity_id=activity_id)
        print(
            f"[ok] {activity_id} @ {item['start']} | 距离 {evidence['l0']['total_distance_m']}m "
            f"| 配速 {evidence['l1']['avg_pace_per_100m_s']}s/100m | SWOLF {evidence['l1']['avg_swolf_derived']}"
        )
    print("当前泳池活动：")
    for act in repo.list_swim_activities(limit=20):
        print("  ", act["activity_id"], act.get("start_time"), act.get("distance"))


if __name__ == "__main__":
    main()
