"""Legacy module alias for :mod:`ksi_core.domains.analytics.defect_candidates`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.analytics import defect_candidates as _canonical
from ksi_core.domains.analytics.defect_candidates import *  # noqa: F403

_sys.modules[__name__] = _canonical
