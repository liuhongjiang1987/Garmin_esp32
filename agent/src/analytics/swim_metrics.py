"""由每一趟计算配速与 SWOLF。实现放在 deploy/garmindb/swimcore，NAS 与本机共用。"""

from __future__ import annotations

import sys
from pathlib import Path

_SWIMCORE_ROOT = Path(__file__).resolve().parents[3] / "deploy" / "garmindb"
if str(_SWIMCORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWIMCORE_ROOT))

from swimcore.metrics import (  # noqa: E402
    SwimLength,
    active_lengths,
    length_swolf,
    make_length,
    pace_per_100m,
    rest_ratio,
    rest_time_s,
    session_avg_pace_s,
    session_avg_swolf,
    session_best_pace_s,
    stroke_halves,
)

__all__ = [
    "SwimLength",
    "active_lengths",
    "length_swolf",
    "make_length",
    "pace_per_100m",
    "rest_ratio",
    "rest_time_s",
    "session_avg_pace_s",
    "session_avg_swolf",
    "session_best_pace_s",
    "stroke_halves",
]
