"""Legacy module alias for :mod:`ksi_core.domains.processing.civil_preflight`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.processing import civil_preflight as _canonical
from ksi_core.domains.processing.civil_preflight import *  # noqa: F403

_sys.modules[__name__] = _canonical
