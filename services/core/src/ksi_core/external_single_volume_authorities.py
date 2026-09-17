"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.quantity import external_single_volume_authorities as _canonical
from ksi_core.domains.external.quantity.external_single_volume_authorities import *  # noqa: F403

_sys.modules[__name__] = _canonical
