"""Legacy module alias for :mod:`ksi_core.identity.auth`."""

from __future__ import annotations

import sys as _sys

from ksi_core.identity import auth as _canonical
from ksi_core.identity.auth import *  # noqa: F403
from ksi_core.identity.auth import _ROLE_PERMISSIONS  # noqa: F401

_sys.modules[__name__] = _canonical
