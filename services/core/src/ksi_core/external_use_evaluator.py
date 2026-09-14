"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.quantity import external_use_evaluator as _canonical
from ksi_core.domains.external.quantity.external_use_evaluator import *  # noqa: F403
from ksi_core.domains.external.quantity.external_use_evaluator import (
    _PairSnapshot as _PairSnapshot,
)

_sys.modules[__name__] = _canonical
