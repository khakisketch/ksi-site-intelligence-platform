"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.ingress import external_display_artifacts as _canonical
from ksi_core.domains.external.ingress.external_display_artifacts import *  # noqa: F403

_sys.modules[__name__] = _canonical
