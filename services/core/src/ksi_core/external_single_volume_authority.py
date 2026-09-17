"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.quantity import external_single_volume_authority as _canonical
from ksi_core.domains.external.quantity.external_single_volume_authority import *  # noqa: F403

_sys.modules[__name__] = _canonical
