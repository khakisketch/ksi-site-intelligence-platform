"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.authority import external_authority_preflight as _canonical
from ksi_core.domains.external.authority.external_authority_preflight import *  # noqa: F403

if __name__ == "__main__":
    raise SystemExit(_canonical.main())

_sys.modules[__name__] = _canonical
