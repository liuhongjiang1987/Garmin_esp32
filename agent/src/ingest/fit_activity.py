"""从泳池游泳 FIT 读取每一趟。实现放在 deploy/garmindb/swimcore，NAS 与本机共用。"""

from __future__ import annotations

import sys
from pathlib import Path

_SWIMCORE_ROOT = Path(__file__).resolve().parents[3] / "deploy" / "garmindb"
if str(_SWIMCORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWIMCORE_ROOT))

from swimcore.fit_activity import FitSwimActivity, read_swim_fit  # noqa: E402

__all__ = ["FitSwimActivity", "read_swim_fit"]
