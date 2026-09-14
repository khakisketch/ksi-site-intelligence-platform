"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.workflow import external_reobservation_proposals as _canonical
from ksi_core.domains.external.workflow.external_reobservation_proposals import *  # noqa: F403
from ksi_core.domains.external.workflow.external_reobservation_proposals import (
    verify_external_reobservation_graph as verify_external_reobservation_graph,
)

_sys.modules[__name__] = _canonical
