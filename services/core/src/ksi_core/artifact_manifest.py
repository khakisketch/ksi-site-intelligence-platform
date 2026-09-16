"""Legacy module alias for :mod:`ksi_core.domains.artifacts.artifact_manifest`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.artifacts import artifact_manifest as _canonical
from ksi_core.domains.artifacts.artifact_manifest import *  # noqa: F403

_sys.modules[__name__] = _canonical
