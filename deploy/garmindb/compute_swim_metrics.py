"""同步结束后计算新的泳池游泳指标。

在容器里由入口在导入成功后调用。本机挂着 NAS 共享时也可以单独运行。
已经写入 swim_evidence.db 的活动直接跳过。档案不在这个库里。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from swimcore.evidence import build_fit_evidence, enriched_lap_rows, length_rows
from swimcore.fit_activity import read_swim_fit


_SCHEMA = """
CREATE TABLE IF NOT EXISTS swim_lengths (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id TEXT NOT NULL,
  length_index INTEGER NOT NULL,
  length_type TEXT,
  swim_stroke TEXT,
  total_strokes INTEGER,
  avg_speed_mps REAL,
  avg_swimming_cadence INTEGER,
  total_elapsed_s REAL,
  total_timer_s REAL,
  is_active INTEGER NOT NULL DEFAULT 0,
  UNIQUE(activity_id, length_index)
);
CREATE TABLE IF NOT EXISTS swim_laps_enriched (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  activity_id TEXT NOT NULL,
  lap_index INTEGER NOT NULL,
  distance_m REAL,
  elapsed_s REAL,
  timer_s REAL,
  pace_per_100m_s REAL,
  avg_hr INTEGER,
  max_hr INTEGER,
  total_strokes INTEGER,
  swim_stroke_hint TEXT,
  swolf_derived REAL,
  is_rest_lap INTEGER NOT NULL DEFAULT 0,
  UNIQUE(activity_id, lap_index)
);
CREATE TABLE IF NOT EXISTS activity_evidence (
  activity_id TEXT PRIMARY KEY,
  evidence_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _locations() -> tuple[Path, Path, Path]:
    """容器内用 /root，本机用已挂载的 NAS home 共享。"""
    if Path("/root/HealthData/DBs/garmin_activities.db").is_file():
        base = Path("/root/HealthData")
    else:
        base = Path("/Volumes/home/garmindb/home/HealthData")
    return (
        base / "DBs" / "garmin_activities.db",
        base / "FitFiles" / "Activities",
        base / "DBs" / "swim_evidence.db",
    )


def _local_start(value: str) -> str:
    """收成 YYYY-MM-DD HH:MM:SS。"""
    text = str(value).strip().replace("T", " ")
    if "." in text:
        text = text.split(".", 1)[0]
    return text[:19]


def _swim_rows(activities_db: Path) -> list[tuple[str, str]]:
    connection = sqlite3.connect(f"file:{activities_db}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT activity_id, start_time
            FROM activities
            WHERE sport = 'swimming' AND sub_sport = 'lap_swimming'
            ORDER BY start_time
            """
        ).fetchall()
    finally:
        connection.close()
    return [(str(activity_id), _local_start(start_time)) for activity_id, start_time in rows]


def _existing_ids(evidence_db: Path) -> set[str]:
    if not evidence_db.is_file():
        return set()
    connection = sqlite3.connect(f"file:{evidence_db}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT activity_id FROM activity_evidence").fetchall()
    except sqlite3.OperationalError:
        return set()
    finally:
        connection.close()
    return {str(row[0]) for row in rows}


def _store(connection: sqlite3.Connection, activity_id: str, evidence: dict, lengths: list[dict]) -> None:
    """覆盖一场的证据和趟数据。"""
    now = datetime.now(timezone.utc).isoformat()
    connection.execute("DELETE FROM swim_lengths WHERE activity_id = ?", (activity_id,))
    connection.execute("DELETE FROM swim_laps_enriched WHERE activity_id = ?", (activity_id,))
    connection.executemany(
        """
        INSERT INTO swim_lengths(
            activity_id, length_index, length_type, swim_stroke, total_strokes,
            avg_speed_mps, avg_swimming_cadence, total_elapsed_s, total_timer_s, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                activity_id,
                item["length_index"],
                item.get("length_type"),
                item.get("swim_stroke"),
                item.get("total_strokes"),
                item.get("avg_speed_mps"),
                item.get("avg_swimming_cadence"),
                item.get("total_elapsed_s"),
                item.get("total_timer_s"),
                item.get("is_active", 0),
            )
            for item in lengths
        ],
    )
    connection.executemany(
        """
        INSERT INTO swim_laps_enriched(
            activity_id, lap_index, distance_m, elapsed_s, timer_s, pace_per_100m_s,
            avg_hr, max_hr, total_strokes, swim_stroke_hint, swolf_derived, is_rest_lap
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                activity_id,
                item["lap_index"],
                item.get("distance_m"),
                item.get("elapsed_s"),
                item.get("timer_s"),
                item.get("pace_per_100m_s"),
                item.get("avg_hr"),
                item.get("max_hr"),
                item.get("total_strokes"),
                item.get("swim_stroke_hint"),
                item.get("swolf_derived"),
                item.get("is_rest_lap", 0),
            )
            for item in enriched_lap_rows(evidence)
        ],
    )
    connection.execute(
        """
        INSERT INTO activity_evidence(activity_id, evidence_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(activity_id) DO UPDATE SET
            evidence_json = excluded.evidence_json,
            updated_at = excluded.updated_at
        """,
        (activity_id, json.dumps(evidence, ensure_ascii=False), now),
    )


def main() -> None:
    activities_db, fit_dir, evidence_db = _locations()
    if not activities_db.is_file():
        raise SystemExit(f"找不到活动库：{activities_db}")
    if not fit_dir.is_dir():
        raise SystemExit(f"找不到 FIT 目录：{fit_dir}")
    evidence_db.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_ids(evidence_db)
    connection = sqlite3.connect(evidence_db)
    connection.executescript(_SCHEMA)
    written = 0
    skipped = 0
    failed: list[str] = []
    try:
        for activity_id, start_time in _swim_rows(activities_db):
            if activity_id in existing:
                skipped += 1
                continue
            fit_path = fit_dir / f"{activity_id}_ACTIVITY.fit"
            try:
                activity = read_swim_fit(fit_path, activity_id)
                evidence = build_fit_evidence(activity, start_time)
                if not evidence["laps"]:
                    raise ValueError("没有游泳趟")
                _store(connection, activity_id, evidence, length_rows(activity))
                connection.commit()
            except Exception as error:
                connection.rollback()
                failed.append(f"{activity_id}: {error}")
                continue
            written += 1
            print(f"已计算 {start_time} {activity_id}")
    finally:
        connection.close()
    print(f"指标计算完成：新写入 {written} 场，跳过 {skipped} 场，失败 {len(failed)} 场")
    for item in failed:
        print(item)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
