"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.ingress import external_reconstruction as _canonical
from ksi_core.domains.external.ingress.external_reconstruction import *  # noqa: F403
from ksi_core.domains.external.ingress.external_reconstruction import _event_digest  # noqa: F401

_sys.modules[__name__] = _canonical
