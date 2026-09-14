"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.authority import external_authority_operations as _canonical
from ksi_core.domains.external.authority.external_authority_operations import *  # noqa: F403

_sys.modules[__name__] = _canonical
