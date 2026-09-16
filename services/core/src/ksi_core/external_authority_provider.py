"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.authority import external_authority_provider as _canonical
from ksi_core.domains.external.authority.external_authority_provider import *  # noqa: F403
from ksi_core.domains.external.authority.external_authority_provider import _load  # noqa: F401

_sys.modules[__name__] = _canonical
