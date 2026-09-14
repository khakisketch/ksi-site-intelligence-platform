"""Legacy module alias for :mod:`ksi_core.domains.artifacts.evidence_s3`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.artifacts import evidence_s3 as _canonical
from ksi_core.domains.artifacts.evidence_s3 import *  # noqa: F403

_sys.modules[__name__] = _canonical
