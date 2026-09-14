"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.quantity import external_use_decisions as _canonical
from ksi_core.domains.external.quantity.external_use_decisions import *  # noqa: F403

_sys.modules[__name__] = _canonical
