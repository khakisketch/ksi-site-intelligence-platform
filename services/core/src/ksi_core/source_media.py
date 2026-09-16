"""Legacy module alias for :mod:`ksi_core.domains.artifacts.source_media`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.artifacts import source_media as _canonical
from ksi_core.domains.artifacts.source_media import *  # noqa: F403
from ksi_core.domains.artifacts.source_media import (
    _BATCH_STATUS as _BATCH_STATUS,
)
from ksi_core.domains.artifacts.source_media import (
    _SEAL_STATUS as _SEAL_STATUS,
)

_sys.modules[__name__] = _canonical
