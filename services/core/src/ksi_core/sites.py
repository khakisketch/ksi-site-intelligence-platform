"""Legacy module alias for :mod:`ksi_core.domains.sites.sites`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.sites import sites as _canonical
from ksi_core.domains.sites.sites import *  # noqa: F403

_sys.modules[__name__] = _canonical
