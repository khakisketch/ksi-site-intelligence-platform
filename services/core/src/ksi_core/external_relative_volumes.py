"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.quantity import external_relative_volumes as _canonical
from ksi_core.domains.external.quantity.external_relative_volumes import *  # noqa: F403
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeExecutionActivator as ExternalRelativeVolumeExecutionActivator,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeInputCapabilityIssuer as ExternalRelativeVolumeInputCapabilityIssuer,
)

_sys.modules[__name__] = _canonical
