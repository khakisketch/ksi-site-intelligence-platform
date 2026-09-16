"""Legacy module alias for :mod:`ksi_core.identity.oidc`."""

from __future__ import annotations

import sys as _sys

from ksi_core.identity import oidc as _canonical
from ksi_core.identity.oidc import *  # noqa: F403

_sys.modules[__name__] = _canonical
