"""Legacy module alias for :mod:`ksi_core.domains.processing.processing_resource_policy`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.processing import processing_resource_policy as _canonical
from ksi_core.domains.processing.processing_resource_policy import *  # noqa: F403

_sys.modules[__name__] = _canonical
