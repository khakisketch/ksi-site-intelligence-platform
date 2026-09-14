"""Legacy module alias for :mod:`ksi_core.acquisition.capture_quality_reports`."""
from __future__ import annotations

import sys as _sys

from ksi_core.acquisition import capture_quality_reports as _canonical
from ksi_core.acquisition.capture_quality_reports import *  # noqa: F403

_sys.modules[__name__] = _canonical
