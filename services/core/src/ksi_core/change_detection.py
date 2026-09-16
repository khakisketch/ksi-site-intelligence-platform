"""Legacy module alias for :mod:`ksi_core.domains.analytics.change_detection`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.analytics import change_detection as _canonical
from ksi_core.domains.analytics.change_detection import *  # noqa: F403

_sys.modules[__name__] = _canonical
