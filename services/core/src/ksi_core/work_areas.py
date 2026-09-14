"""Legacy module alias for :mod:`ksi_core.domains.sites.work_areas`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.sites import work_areas as _canonical
from ksi_core.domains.sites.work_areas import *  # noqa: F403
from ksi_core.domains.sites.work_areas import (
    WorkAreaStatus as WorkAreaStatus,
)

_sys.modules[__name__] = _canonical
