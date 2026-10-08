"""Legacy module alias for :mod:`ksi_core.domains.workspace.copilot_openai`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.workspace import copilot_openai as _canonical
from ksi_core.domains.workspace.copilot_openai import *  # noqa: F403

_sys.modules[__name__] = _canonical
