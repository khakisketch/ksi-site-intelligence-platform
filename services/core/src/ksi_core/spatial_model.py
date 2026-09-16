"""Legacy module alias for :mod:`ksi_core.domains.processing.spatial_model`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.processing import spatial_model as _canonical
from ksi_core.domains.processing.spatial_model import *  # noqa: F403
from ksi_core.domains.processing.spatial_model import (
    _JOB_STATUS_SITE_ADVANCE as _JOB_STATUS_SITE_ADVANCE,
)

_sys.modules[__name__] = _canonical
