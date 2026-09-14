"""Legacy module alias for :mod:`ksi_core.domains.design.design_conformance_reports`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.design import design_conformance_reports as _canonical
from ksi_core.domains.design.design_conformance_reports import *  # noqa: F403

_sys.modules[__name__] = _canonical
