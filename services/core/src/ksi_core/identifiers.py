"""Legacy module alias for :mod:`ksi_core.foundation.identifiers`."""

from __future__ import annotations

import sys as _sys

from ksi_core.foundation import identifiers as _canonical
from ksi_core.foundation.identifiers import *  # noqa: F403

_sys.modules[__name__] = _canonical
