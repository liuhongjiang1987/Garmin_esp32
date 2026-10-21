"""把 FIT 游泳收成教练证据。实现放在 deploy/garmindb/swimcore，NAS 与本机共用。"""

from __future__ import annotations

import sys
from pathlib import Path

_SWIMCORE_ROOT = Path(__file__).resolve().parents[3] / "deploy" / "garmindb"
if str(_SWIMCORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SWIMCORE_ROOT))

from swimcore.evidence import build_fit_evidence, enriched_lap_rows, length_rows  # noqa: E402

__all__ = ["build_fit_evidence", "enriched_lap_rows", "length_rows"]
