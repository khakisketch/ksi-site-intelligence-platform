"""Legacy module alias for :mod:`ksi_core.domains.missions.mission_records`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.missions import mission_records as _canonical
from ksi_core.domains.missions.mission_records import *  # noqa: F403
from ksi_core.domains.missions.mission_records import (
    IssuanceAuthorizationWitness as IssuanceAuthorizationWitness,
)

_sys.modules[__name__] = _canonical
