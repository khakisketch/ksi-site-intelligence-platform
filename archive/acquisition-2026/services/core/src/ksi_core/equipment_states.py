"""Legacy module alias for :mod:`ksi_core.domains.observations.equipment_states`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.observations import equipment_states as _canonical
from ksi_core.domains.observations.equipment_states import *  # noqa: F403

_sys.modules[__name__] = _canonical
