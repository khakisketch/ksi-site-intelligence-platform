"""Legacy module alias for :mod:`ksi_core.domains.artifacts.artifact_refs`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.artifacts import artifact_refs as _canonical
from ksi_core.domains.artifacts.artifact_refs import *  # noqa: F403

_sys.modules[__name__] = _canonical
