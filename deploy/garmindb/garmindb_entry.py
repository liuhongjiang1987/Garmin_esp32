"""容器入口。先增量导入活动，导入成功后再计算新的游泳指标。"""

import shutil
import sys
from pathlib import Path


# 补丁、指标脚本都放在 /opt，避免和挂载进来的 /root 数据目录混在一起。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from incremental_activity_import import install
import runpy


install()

script = shutil.which("garmindb_cli.py")
if script is None:
    raise SystemExit("找不到 garmindb_cli.py，镜像里的 GarminDB 没有装好")

# 原脚本用 sys.exit 结束。接住退出码，成功且这次带了导入时才计算指标。
exit_code = 0
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    exit_code = exc.code if isinstance(exc.code, int) else 0

if exit_code == 0 and "--import" in sys.argv:
    from compute_swim_metrics import main as compute_metrics

    try:
        compute_metrics()
    except SystemExit as exc:
        metric_code = exc.code if isinstance(exc.code, int) else 1
        if metric_code:
            exit_code = metric_code

raise SystemExit(exit_code)
