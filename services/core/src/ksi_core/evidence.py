"""Legacy module alias for :mod:`ksi_core.domains.artifacts.evidence`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.artifacts import evidence as _canonical
from ksi_core.domains.artifacts.evidence import *  # noqa: F403

_sys.modules[__name__] = _canonical
