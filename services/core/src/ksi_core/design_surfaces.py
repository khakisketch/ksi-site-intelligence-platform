"""Legacy module alias for :mod:`ksi_core.domains.design.design_surfaces`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.design import design_surfaces as _canonical
from ksi_core.domains.design.design_surfaces import *  # noqa: F403
from ksi_core.domains.design.design_surfaces import (
    _OBSERVATION_STATUS as _OBSERVATION_STATUS,
)
from ksi_core.domains.design.design_surfaces import (
    _REGISTER_STATUS as _REGISTER_STATUS,
)
from ksi_core.domains.design.design_surfaces import (
    _SEAL_STATUS as _SEAL_STATUS,
)

_sys.modules[__name__] = _canonical
