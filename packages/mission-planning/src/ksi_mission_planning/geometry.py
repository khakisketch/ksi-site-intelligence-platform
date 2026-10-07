"""Legacy alias — canonical AOI geometry lives in ksi_geo_core.aoi.

This module object is exactly ``ksi_geo_core.aoi`` (``sys.modules`` alias), so
legacy callers share class and helper state with the neutral implementation —
monkeypatching through either path reaches the same globals. The explicit
imports below mirror the canonical namespace (including private helpers and
limit constants) so static analysis sees the same surface the runtime alias
provides. Do not add new definitions here; extend the canonical module instead.
"""

from __future__ import annotations

import sys as _sys

from ksi_geo_core import aoi as _canonical_aoi
from ksi_geo_core.aoi import _EPSILON_M as _EPSILON_M
from ksi_geo_core.aoi import _EPSILON_M2 as _EPSILON_M2
from ksi_geo_core.aoi import _MAX_ABS_LATITUDE_DEG as _MAX_ABS_LATITUDE_DEG
from ksi_geo_core.aoi import _MAX_EXTENT_M as _MAX_EXTENT_M
from ksi_geo_core.aoi import _MAX_VERTICES as _MAX_VERTICES
from ksi_geo_core.aoi import AreaOfInterest as AreaOfInterest
from ksi_geo_core.aoi import GeoPoint as GeoPoint
from ksi_geo_core.aoi import _on_segment as _on_segment
from ksi_geo_core.aoi import _orient as _orient
from ksi_geo_core.aoi import _segments_intersect as _segments_intersect

_sys.modules[__name__] = _canonical_aoi
