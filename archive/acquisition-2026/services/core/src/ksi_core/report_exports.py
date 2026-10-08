"""Legacy module alias for :mod:`ksi_core.domains.design.report_exports`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.design import report_exports as _canonical
from ksi_core.domains.design.report_exports import *  # noqa: F403

_sys.modules[__name__] = _canonical
