"""Legacy module alias for :mod:`ksi_core.domains.processing.processing_profiles`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.processing import processing_profiles as _canonical
from ksi_core.domains.processing.processing_profiles import *  # noqa: F403

_sys.modules[__name__] = _canonical
