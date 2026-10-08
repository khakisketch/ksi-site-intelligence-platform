"""Legacy module alias for :mod:`ksi_core.domains.workspace.copilot_conversations`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.workspace import copilot_conversations as _canonical
from ksi_core.domains.workspace.copilot_conversations import *  # noqa: F403

_sys.modules[__name__] = _canonical
