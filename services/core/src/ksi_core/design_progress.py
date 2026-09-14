"""Legacy module alias for :mod:`ksi_core.domains.design.design_progress`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.design import design_progress as _canonical
from ksi_core.domains.design.design_progress import *  # noqa: F403
from ksi_core.domains.design.design_progress import (
    _zone_progress as _zone_progress,
)

_sys.modules[__name__] = _canonical
