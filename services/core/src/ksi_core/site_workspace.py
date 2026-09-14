"""Legacy module alias for :mod:`ksi_core.domains.workspace.site_workspace`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.workspace import site_workspace as _canonical
from ksi_core.domains.workspace.site_workspace import *  # noqa: F403

_sys.modules[__name__] = _canonical
