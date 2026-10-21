"""手动计算游泳指标。NAS 定时任务成功导入后会自动做同样的事。"""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    script = Path(__file__).resolve().parents[1] / "deploy" / "garmindb" / "compute_swim_metrics.py"
    runpy.run_path(str(script), run_name="__main__")
