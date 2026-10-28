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

-- 单次分析：同步后入队；状态 analyzing|succeeded|failed；报告另表只读给表盘
CREATE TABLE IF NOT EXISTS session_analysis_jobs (
  activity_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_analysis_reports (
  activity_id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  report_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 趋势分析：按跨度入队与存报告
-- 趋势：默认不入队；用户点选跨度后 status=analyzing；新同步作废 succeeded→idle
CREATE TABLE IF NOT EXISTS trend_analysis_jobs (
  span TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trend_analysis_reports (
  span TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  report_json TEXT NOT NULL,
  data_fingerprint TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 综合建议：训练计划异步任务（每运动员一条当前任务）
CREATE TABLE IF NOT EXISTS advice_plan_jobs (
  athlete_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  error TEXT,
  plan_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def init_coach_db(db_path: Path) -> None:
    """创建 coach.db 并初始化 schema。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        # 旧库补列：趋势报告数据指纹，用于「无新数据则复用缓存」
        cols = {row[1] for row in conn.execute("PRAGMA table_info(trend_analysis_reports)")}
        if "data_fingerprint" not in cols:
            conn.execute(
                "ALTER TABLE trend_analysis_reports ADD COLUMN data_fingerprint TEXT"
            )
        conn.commit()

