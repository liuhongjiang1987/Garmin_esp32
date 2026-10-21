# 模块级说明：集中管理环境变量、路径与运行配置，避免在业务代码中硬编码。

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """运行配置。"""

    project_root: Path
    data_root: Path
    garmin_db_path: Path
    garmin_activities_db_path: Path
    coach_db_path: Path
    swim_evidence_db_path: Path | None
    csv_sample_path: Path
    model_name: str
    model_base_url: str
    model_api_key: str


def load_settings() -> Settings:
    """加载 `.env` 与默认路径。"""
    project_root = Path(__file__).resolve().parents[1]
    repo_root = project_root.parent

    load_dotenv(project_root / ".env")

    data_root = Path(os.getenv("GARMIN_DATA_ROOT", str(repo_root / "data" / "garmindb_fixtures")))
    garmin_db_path = Path(os.getenv("GARMIN_DB_PATH", str(data_root / "garmin.db")))
    garmin_activities_db_path = Path(
        os.getenv("GARMIN_ACTIVITIES_DB_PATH", str(data_root / "garmin_activities.db"))
    )
    coach_db_path = Path(os.getenv("COACH_DB_PATH", str(project_root / "data" / "coach.db")))
    # 逐行注释：NAS 同步容器把算好的游泳证据写在共享目录。挂载存在时教练查这份，不再查本机样例证据。
    evidence_default = Path("/Volumes/home/garmindb/home/HealthData/DBs/swim_evidence.db")
    evidence_setting = os.getenv("SWIM_EVIDENCE_DB")
    swim_evidence_db_path = Path(evidence_setting) if evidence_setting else evidence_default
    if not swim_evidence_db_path.is_file():
        swim_evidence_db_path = None
    return Settings(
        project_root=project_root,
        data_root=data_root,
        garmin_db_path=garmin_db_path,
        garmin_activities_db_path=garmin_activities_db_path,
        coach_db_path=coach_db_path,
        swim_evidence_db_path=swim_evidence_db_path,
        csv_sample_path=repo_root / "data" / "activity_638297383.csv",
        model_name=os.getenv("SILICONFLOW_MODEL_ANALYZE", "Qwen/Qwen3-30B-A3B-Instruct-2507"),
        model_base_url=os.getenv("SILICONFLOW_BASE_URL", ""),
        model_api_key=os.getenv("SILICONFLOW_API_KEY", ""),
    )

