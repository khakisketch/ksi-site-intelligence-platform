"""Legacy module alias for :mod:`ksi_core.domains.edge_transport.edge_dispatch`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.edge_transport import edge_dispatch as _canonical
from ksi_core.domains.edge_transport.edge_dispatch import *  # noqa: F403

_sys.modules[__name__] = _canonical
