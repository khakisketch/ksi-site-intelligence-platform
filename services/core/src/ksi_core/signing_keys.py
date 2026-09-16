"""Legacy module alias for :mod:`ksi_core.identity.signing_keys`."""

from __future__ import annotations

import sys as _sys

from ksi_core.identity import signing_keys as _canonical
from ksi_core.identity.signing_keys import *  # noqa: F403

_sys.modules[__name__] = _canonical
