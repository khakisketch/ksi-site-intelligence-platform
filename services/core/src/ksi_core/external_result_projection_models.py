"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.workflow import external_result_projection_models as _canonical
from ksi_core.domains.external.workflow.external_result_projection_models import *  # noqa: F403

_sys.modules[__name__] = _canonical
