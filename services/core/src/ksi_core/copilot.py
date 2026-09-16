"""Legacy module alias for :mod:`ksi_core.domains.workspace.copilot`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.workspace import copilot as _canonical
from ksi_core.domains.workspace.copilot import *  # noqa: F403
from ksi_core.domains.workspace.copilot import (
    CopilotQueryRequest as CopilotQueryRequest,
)

_sys.modules[__name__] = _canonical
