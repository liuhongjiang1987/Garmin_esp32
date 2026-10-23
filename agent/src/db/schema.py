# 模块级说明：定义并初始化 coach.db 的开发期表结构。

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS athlete_profile (
  athlete_id TEXT PRIMARY KEY,
  profile_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS performance_state (
  athlete_id TEXT PRIMARY KEY,
  state_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subjective_memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  athlete_id TEXT NOT NULL,
  activity_id TEXT,
  rpe INTEGER,
  fatigue_note TEXT,
  pain_note TEXT,
  feel_note TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workout_plans (
  plan_id TEXT PRIMARY KEY,
  athlete_id TEXT NOT NULL,
  based_on_activity_id TEXT,
  plan_markdown TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS css_anchors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  athlete_id TEXT NOT NULL,
  css_seconds_per_100m REAL NOT NULL,
  css_pace_text TEXT NOT NULL,
  test_method TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '自测',
  test_date TEXT NOT NULL,
  retest_due TEXT NOT NULL,
  zone_json TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 1
);
"""


def init_coach_db(db_path: Path) -> None:
    """创建 coach.db 并初始化 schema。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

