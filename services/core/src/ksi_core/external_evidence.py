"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.ingress import external_evidence as _canonical
from ksi_core.domains.external.ingress.external_evidence import *  # noqa: F403
from ksi_core.domains.external.ingress.external_evidence import EvidenceItem as EvidenceItem
from ksi_core.domains.external.ingress.external_evidence import EvidenceVerdict as EvidenceVerdict
from ksi_core.domains.external.ingress.external_evidence import (
    ExternalEvidenceDeclarationIntent as ExternalEvidenceDeclarationIntent,
)
from ksi_core.domains.external.ingress.external_evidence import (
    _require_scoped_work_order as _require_scoped_work_order,
)
from ksi_core.domains.external.ingress.external_evidence import _view as _view

_sys.modules[__name__] = _canonical
