"""Legacy module alias for :mod:`ksi_core.domains.artifacts.checkpoint_validations`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.artifacts import checkpoint_validations as _canonical
from ksi_core.domains.artifacts.checkpoint_validations import *  # noqa: F403

_sys.modules[__name__] = _canonical
