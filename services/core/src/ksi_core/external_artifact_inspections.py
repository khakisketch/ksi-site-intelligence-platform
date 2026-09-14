"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.ingress import external_artifact_inspections as _canonical
from ksi_core.domains.external.ingress.external_artifact_inspections import *  # noqa: F403
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    PublicInspectionSnapshot as PublicInspectionSnapshot,
)
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    SealedExternalReconstructionSnapshotPort as SealedExternalReconstructionSnapshotPort,
)

_sys.modules[__name__] = _canonical
