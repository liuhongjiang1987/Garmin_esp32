# 模块级说明：封装固定 SQL，统一访问 GarminDB 只读库与 coach.db 可写库。

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class DbPaths:
    """数据库路径集合。"""

    coach_db: Path
    garmin_db: Path
    garmin_activities_db: Path


class SwimRepository:
    """数据访问仓库。"""

    def __init__(self, db_paths: DbPaths) -> None:
        self._db_paths = db_paths

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_paths.coach_db)
        conn.row_factory = sqlite3.Row
        # 教练容器里不一定有佳明原始库。文件不存在就不要挂，避免把空库建出来。
        if self._db_paths.garmin_db.is_file():
            conn.execute("ATTACH DATABASE ? AS garmin", (str(self._db_paths.garmin_db),))
        if self._db_paths.garmin_activities_db.is_file():
            conn.execute(
                "ATTACH DATABASE ? AS garmin_activities",
                (str(self._db_paths.garmin_activities_db),),
            )
        return conn

    def list_swim_activities(self, limit: int = 10) -> list[dict[str, Any]]:
        """列出游泳活动。"""
        sql = """
        SELECT activity_id, name, sport, sub_sport, distance, laps, avg_hr, max_hr, start_time
        FROM garmin_activities.activities
        WHERE sport = 'swimming'
        ORDER BY start_time DESC
        LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_latest_swim_activity_id(self) -> str | None:
        """获取最近一场已入库游泳的 activity_id。优先看 NAS 自动算好的证据。"""
        from src.config import load_settings

        evidence_db = load_settings().swim_evidence_db_path
        if evidence_db is not None:
            with sqlite3.connect(f"file:{evidence_db}?mode=ro", uri=True) as evidence_conn:
                evidence_conn.row_factory = sqlite3.Row
                rows = evidence_conn.execute(
                    "SELECT activity_id, evidence_json FROM activity_evidence"
                ).fetchall()
        else:
            rows = []
        if not rows:
            with self._connect() as conn:
                rows = conn.execute("SELECT activity_id, evidence_json FROM activity_evidence").fetchall()
        latest_id = None
        latest_start = ""
        for row in rows:
            start_time = str(json.loads(row["evidence_json"]).get("start_time") or "")
            if start_time >= latest_start:
                latest_start = start_time
                latest_id = row["activity_id"]
        if latest_id is not None:
            return latest_id
        activities = self.list_swim_activities(limit=1)
        return activities[0]["activity_id"] if activities else None

    def get_activity_summary(self, activity_id: str) -> dict[str, Any] | None:
        """读取单场摘要。"""
        sql = """
        SELECT activity_id, name, sport, sub_sport, distance, laps, avg_hr, max_hr,
               elapsed_time, moving_time, avg_speed, max_speed, calories, start_time, stop_time
        FROM garmin_activities.activities
        WHERE activity_id = ?
        """
        with self._connect() as conn:
            row = conn.execute(sql, (activity_id,)).fetchone()
        return dict(row) if row else None

    def upsert_evidence(self, activity_id: str, evidence: dict[str, Any]) -> None:
        """写入 evidence JSON。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activity_evidence(activity_id, evidence_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    evidence_json=excluded.evidence_json,
                    updated_at=excluded.updated_at
                """,
                (activity_id, json.dumps(evidence, ensure_ascii=False), datetime.utcnow().isoformat()),
            )
            conn.commit()

    def get_evidence(self, activity_id: str) -> dict[str, Any] | None:
        """读取 evidence JSON。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT evidence_json FROM activity_evidence WHERE activity_id = ?",
                (activity_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["evidence_json"])

    def replace_lengths(self, activity_id: str, lengths: list[dict[str, Any]]) -> None:
        """覆盖写入一场活动的 length 增强数据。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM swim_lengths WHERE activity_id = ?", (activity_id,))
            for item in lengths:
                conn.execute(
                    """
                    INSERT INTO swim_lengths(
                        activity_id, length_index, length_type, swim_stroke, total_strokes,
                        avg_speed_mps, avg_swimming_cadence, total_elapsed_s, total_timer_s, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
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
                    ),
                )
            conn.commit()

    def replace_laps_enriched(self, activity_id: str, laps: list[dict[str, Any]]) -> None:
        """覆盖写入一场活动的 lap 增强数据。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM swim_laps_enriched WHERE activity_id = ?", (activity_id,))
            for item in laps:
                conn.execute(
                    """
                    INSERT INTO swim_laps_enriched(
                        activity_id, lap_index, distance_m, elapsed_s, timer_s, pace_per_100m_s,
                        avg_hr, max_hr, total_strokes, swim_stroke_hint, swolf_derived, is_rest_lap
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
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
                    ),
                )
            conn.commit()

    def upsert_profile(self, athlete_id: str, profile: dict[str, Any]) -> None:
        """写入 profile。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO athlete_profile(athlete_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(athlete_id) DO UPDATE SET
                    profile_json=excluded.profile_json,
                    updated_at=excluded.updated_at
                """,
                (athlete_id, json.dumps(profile, ensure_ascii=False), datetime.utcnow().isoformat()),
            )
            conn.commit()

    def get_profile(self, athlete_id: str) -> dict[str, Any] | None:
        """读取 profile。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM athlete_profile WHERE athlete_id = ?",
                (athlete_id,),
            ).fetchone()
        return json.loads(row["profile_json"]) if row else None

    def upsert_performance_state(self, athlete_id: str, state: dict[str, Any]) -> None:
        """写入表现状态。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO performance_state(athlete_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(athlete_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (athlete_id, json.dumps(state, ensure_ascii=False), datetime.utcnow().isoformat()),
            )
            conn.commit()

    def get_performance_state(self, athlete_id: str) -> dict[str, Any] | None:
        """读取表现状态。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM performance_state WHERE athlete_id = ?",
                (athlete_id,),
            ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def add_subjective_note(
        self,
        athlete_id: str,
        activity_id: str | None,
        rpe: int | None,
        fatigue_note: str | None,
        pain_note: str | None,
        feel_note: str | None,
    ) -> None:
        """写入主观感受记录。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO subjective_memory(
                    athlete_id, activity_id, rpe, fatigue_note, pain_note, feel_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    athlete_id,
                    activity_id,
                    rpe,
                    fatigue_note,
                    pain_note,
                    feel_note,
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def list_subjective_notes(self, athlete_id: str, limit: int = 8) -> list[dict[str, Any]]:
        """读取最近若干条主观训练笔记，按时间倒序。"""
        sql = """
        SELECT activity_id, rpe, fatigue_note, pain_note, feel_note, created_at
        FROM subjective_memory
        WHERE athlete_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (athlete_id, limit)).fetchall()
        return [dict(row) for row in rows]

    # ── CSS 锚点 ──

    def save_css_anchor(self, athlete_id: str, anchor: dict[str, Any]) -> None:
        """保存一条新的 CSS 锚点，并把该运动员的旧锚点标为非当前。"""
        with self._connect() as conn:
            # 把以前的标为非当前
            conn.execute(
                "UPDATE css_anchors SET is_current = 0 WHERE athlete_id = ? AND is_current = 1",
                (athlete_id,),
            )
            conn.execute(
                """
                INSERT INTO css_anchors(
                    athlete_id, css_seconds_per_100m, css_pace_text, test_method,
                    source, test_date, retest_due, zone_json, note, created_at, is_current
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    athlete_id,
                    anchor["css_seconds_per_100m"],
                    anchor["css_pace_text"],
                    anchor["test_method"],
                    anchor.get("source", "自测"),
                    anchor["test_date"],
                    anchor["retest_due"],
                    json.dumps(anchor.get("zones", {}), ensure_ascii=False),
                    anchor.get("note"),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def get_current_css_anchor(self, athlete_id: str) -> dict[str, Any] | None:
        """读取当前生效的 CSS 锚点。"""
        sql = """
        SELECT css_seconds_per_100m, css_pace_text, test_method, source,
               test_date, retest_due, zone_json, note, created_at
        FROM css_anchors
        WHERE athlete_id = ? AND is_current = 1
        ORDER BY created_at DESC
        LIMIT 1
        """
        with self._connect() as conn:
            row = conn.execute(sql, (athlete_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["zones"] = json.loads(result.pop("zone_json"))
        return result

    def list_css_history(self, athlete_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """读取 CSS 锚点历史，最新在前。"""
        sql = """
        SELECT css_seconds_per_100m, css_pace_text, test_method, source,
               test_date, retest_due, zone_json, note, created_at, is_current
        FROM css_anchors
        WHERE athlete_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (athlete_id, limit)).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["zones"] = json.loads(item.pop("zone_json"))
            results.append(item)
        return results

