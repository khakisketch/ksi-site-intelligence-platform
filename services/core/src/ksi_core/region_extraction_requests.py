"""Legacy module alias for :mod:`ksi_core.domains.design.region_extraction_requests`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.design import region_extraction_requests as _canonical
from ksi_core.domains.design.region_extraction_requests import *  # noqa: F403

_sys.modules[__name__] = _canonical
