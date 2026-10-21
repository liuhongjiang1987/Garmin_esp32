"""活动导入增量补丁。

GarminDB 自带的 latest 只保留最近 24 小时内修改过的文件。
第一次同步当天，目录里的活动文件都会被反复解析。

本模块在 --latest 导入时改成另一条规则：
文件名里的活动编号已经在 garmin_activities.db 的 activities 表中，就跳过。
尚未入库的文件不受 24 小时限制，下次运行仍会导入。
"""

import logging
import os
import re
import sqlite3
from pathlib import Path


logger = logging.getLogger("incremental_activity_import")

# 摘要是 activity_<id>.json，详情是 activity_details_<id>.json。
# Garmin 下载的 FIT 实际文件名是 <id>_ACTIVITY.fit，不是 <id>.fit。
_ACTIVITY_FILE = re.compile(
    r"(?:activity_details_|activity_)?(?P<activity_id>\d+)(?:_ACTIVITY)?\.(?:json|fit|tcx)$",
    re.IGNORECASE,
)


def activity_id_from_path(file_path):
    """从活动文件名取出 activity_id。对不上的文件返回 None，调用方应保留它。"""
    match = _ACTIVITY_FILE.search(os.path.basename(file_path))
    if match is None:
        return None
    return match.group("activity_id")


def activities_db_path():
    """定位活动库。容器里是 /root/HealthData/DBs，也允许用环境变量覆盖。"""
    override = os.environ.get("GARMIN_ACTIVITIES_DB")
    if override:
        return Path(override)
    return Path.home() / "HealthData" / "DBs" / "garmin_activities.db"


def existing_activity_ids(db_path=None):
    """读取已经入库的活动编号。库不存在或表还没建好时返回空集，让导入照常进行。"""
    path = Path(db_path) if db_path is not None else activities_db_path()
    if not path.is_file():
        return set()
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT activity_id FROM activities").fetchall()
    except sqlite3.Error as error:
        logger.warning("读取已导入活动失败，本次不跳过文件：%s", error)
        return set()
    finally:
        connection.close()
    return {str(row[0]) for row in rows}


def pending_activity_files(file_names, known_ids):
    """留下尚未入库的活动文件。认不出活动编号的文件原样保留。"""
    pending = []
    for file_name in file_names:
        activity_id = activity_id_from_path(file_name)
        if activity_id is not None and activity_id in known_ids:
            continue
        pending.append(file_name)
    return pending


def _rescan(input_dir, file_regex, recursive):
    """按文件名重新列出目录，不再使用 GarminDB 的 24 小时过滤。"""
    from idbutils import FileProcessor

    return FileProcessor.dir_to_files(input_dir, file_regex, False, recursive)


def _apply_incremental(owner, input_dir, file_regex, recursive):
    """用“未入库”文件列表替换 latest 选中的最近 24 小时文件。"""
    known_ids = existing_activity_ids()
    all_files = _rescan(input_dir, file_regex, recursive)
    pending = pending_activity_files(all_files, known_ids)
    skipped = len(all_files) - len(pending)
    owner.file_names = pending
    logger.info(
        "增量导入：目录 %d 个活动文件，跳过已入库 %d 个，待导入 %d 个",
        len(all_files),
        skipped,
        len(pending),
    )


def install():
    """包住活动 JSON 和 FIT 的构造函数。只在调用方传入 latest=True 时生效。"""
    from garmindb.fit_data import FitData
    from garmindb.garmin_json_data import GarminJsonActivityData
    import fitfile

    original_json_init = GarminJsonActivityData.__init__
    original_fit_init = FitData.__init__

    def json_init(self, db_params, file_regex, input_dir, latest, measurement_system, debug):
        # 先走原构造，保证数据库会话和字段转换都还在。
        original_json_init(self, db_params, file_regex, input_dir, latest, measurement_system, debug)
        if latest:
            _apply_incremental(self, input_dir, file_regex, False)

    def fit_init(self, input_dir, debug, latest=False, recursive=False, fit_types=None,
                 measurement_system=fitfile.field_enums.DisplayMeasure.metric):
        original_fit_init(
            self, input_dir, debug, latest, recursive, fit_types, measurement_system
        )
        # 监测 FIT 的文件名不是活动编号，认不出来就不会被跳过。
        if latest:
            _apply_incremental(self, input_dir, fitfile.file.name_regex, recursive)

    GarminJsonActivityData.__init__ = json_init
    FitData.__init__ = fit_init
    logger.info("已启用活动增量导入：按 activity_id 跳过已入库文件")
