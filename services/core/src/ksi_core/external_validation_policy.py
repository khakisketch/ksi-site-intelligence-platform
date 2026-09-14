"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.ingress import external_validation_policy as _canonical
from ksi_core.domains.external.ingress.external_validation_policy import *  # noqa: F403

_sys.modules[__name__] = _canonical
