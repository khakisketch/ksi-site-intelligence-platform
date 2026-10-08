"""Legacy module alias for :mod:`ksi_core.domains.edge_transport.edge_sync`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.edge_transport import edge_sync as _canonical
from ksi_core.domains.edge_transport.edge_sync import *  # noqa: F403
from ksi_core.domains.edge_transport.edge_sync import (
    _STATUS as _STATUS,
)
from ksi_core.domains.edge_transport.edge_sync import (
    _WRITE as _WRITE,
)
from ksi_core.domains.edge_transport.edge_sync import (
    _payload_depth_violation as _payload_depth_violation,
)

_sys.modules[__name__] = _canonical
