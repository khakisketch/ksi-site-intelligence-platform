"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.composition import app_factory as _canonical
from ksi_core.composition.app_factory import *  # noqa: F403
from ksi_core.composition.app_factory import _ASSEMBLY_REQUIREMENTS as _ASSEMBLY_REQUIREMENTS
from ksi_core.composition.app_factory import create_app as create_app

_sys.modules[__name__] = _canonical
