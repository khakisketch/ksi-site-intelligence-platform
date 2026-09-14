"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.quantity import (
    external_relative_volume_s3_capabilities as _canonical,
)
from ksi_core.domains.external.quantity.external_relative_volume_s3_capabilities import *  # noqa: F403

_sys.modules[__name__] = _canonical
