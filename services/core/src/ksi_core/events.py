"""Legacy module alias for :mod:`ksi_core.domains.observations.events`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.observations import events as _canonical
from ksi_core.domains.observations.events import *  # noqa: F403
from ksi_core.domains.observations.events import (
    _EDGE_ASSERTABLE_STATUSES as _EDGE_ASSERTABLE_STATUSES,
)
from ksi_core.domains.observations.events import _STATUS as _STATUS
from ksi_core.domains.observations.events import (
    EventStoreRecoveryError as EventStoreRecoveryError,
)
from ksi_core.domains.observations.events import (
    _geometry_is_degenerate as _geometry_is_degenerate,
)

_sys.modules[__name__] = _canonical
