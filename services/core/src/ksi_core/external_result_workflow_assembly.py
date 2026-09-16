"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.authority import external_result_workflow_assembly as _canonical
from ksi_core.domains.external.authority.external_result_workflow_assembly import *  # noqa: F403

_sys.modules[__name__] = _canonical
