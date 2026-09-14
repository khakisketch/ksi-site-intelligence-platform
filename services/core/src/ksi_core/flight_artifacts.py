"""Legacy module alias for :mod:`ksi_core.domains.missions.flight_artifacts`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.missions import flight_artifacts as _canonical
from ksi_core.domains.missions.flight_artifacts import *  # noqa: F403

_sys.modules[__name__] = _canonical
