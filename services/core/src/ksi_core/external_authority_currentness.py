"""Legacy module alias for :mod:`ksi_core.foundation.currentness`."""

from __future__ import annotations

import sys as _sys

from ksi_core.foundation import currentness as _canonical
from ksi_core.foundation.currentness import *  # noqa: F403

_sys.modules[__name__] = _canonical
