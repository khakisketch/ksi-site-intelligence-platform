"""Legacy module alias for :mod:`ksi_core.domains.missions.coverage_reports`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.missions import coverage_reports as _canonical
from ksi_core.domains.missions.coverage_reports import *  # noqa: F403
from ksi_core.domains.missions.coverage_reports import (
    _STATUS as _STATUS,
)

_sys.modules[__name__] = _canonical
