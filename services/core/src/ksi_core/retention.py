"""Legacy module alias for :mod:`ksi_core.foundation.retention`."""

from __future__ import annotations

import sys as _sys

from ksi_core.foundation import retention as _canonical
from ksi_core.foundation.retention import *  # noqa: F403

_sys.modules[__name__] = _canonical
