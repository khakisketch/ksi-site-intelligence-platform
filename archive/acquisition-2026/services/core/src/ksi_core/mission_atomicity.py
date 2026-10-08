"""Legacy module alias for :mod:`ksi_core.domains.missions.mission_atomicity`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.missions import mission_atomicity as _canonical
from ksi_core.domains.missions.mission_atomicity import *  # noqa: F403

_sys.modules[__name__] = _canonical
