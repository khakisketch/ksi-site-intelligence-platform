"""Legacy module alias for :mod:`ksi_core.domains.analytics.volume_reports`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.analytics import volume_reports as _canonical
from ksi_core.domains.analytics.volume_reports import *  # noqa: F403

_sys.modules[__name__] = _canonical
