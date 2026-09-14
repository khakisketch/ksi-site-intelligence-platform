"""Legacy module alias for :mod:`ksi_core.domains.sites.work_inbox`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.sites import work_inbox as _canonical
from ksi_core.domains.sites.work_inbox import *  # noqa: F403

_sys.modules[__name__] = _canonical
