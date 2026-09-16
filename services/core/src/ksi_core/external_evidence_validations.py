"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.ingress import external_evidence_validations as _canonical
from ksi_core.domains.external.ingress.external_evidence_validations import *  # noqa: F403
from ksi_core.domains.external.ingress.external_evidence_validations import (
    _event_digest as _event_digest,
)

_sys.modules[__name__] = _canonical
