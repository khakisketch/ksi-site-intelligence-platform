"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.composition import assembly as _canonical
from ksi_core.composition.assembly import *  # noqa: F403
from ksi_core.composition.assembly import (
    ExternalAuthorityCurrentnessCoordinator as ExternalAuthorityCurrentnessCoordinator,
)
from ksi_core.composition.assembly import (
    ObservationWorkOrderStore as ObservationWorkOrderStore,
)
from ksi_core.composition.assembly import assemble_app as assemble_app
from ksi_core.composition.assembly import cli_optional_positive as cli_optional_positive

_sys.modules[__name__] = _canonical
