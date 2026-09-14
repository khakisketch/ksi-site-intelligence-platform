"""Legacy module alias for :mod:`ksi_core.domains.sites.organization_work_roster`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.sites import organization_work_roster as _canonical
from ksi_core.domains.sites.organization_work_roster import *  # noqa: F403

_sys.modules[__name__] = _canonical
