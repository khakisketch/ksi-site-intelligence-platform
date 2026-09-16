"""Legacy module alias for :mod:`ksi_core.domains.processing.civil_readiness`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.processing import civil_readiness as _canonical
from ksi_core.domains.processing.civil_readiness import *  # noqa: F403

_sys.modules[__name__] = _canonical
