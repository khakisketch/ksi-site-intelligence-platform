"""Legacy module alias for :mod:`ksi_core.domains.missions.mission_plans`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.missions import mission_plans as _canonical
from ksi_core.domains.missions.mission_plans import *  # noqa: F403
from ksi_core.domains.missions.mission_plans import (
    _require_wayline_takeoff_height_compatible as _require_wayline_takeoff_height_compatible,
)

_sys.modules[__name__] = _canonical
