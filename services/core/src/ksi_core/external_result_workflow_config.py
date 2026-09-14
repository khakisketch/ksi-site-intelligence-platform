"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.domains.external.authority import external_result_workflow_config as _canonical
from ksi_core.domains.external.authority.external_result_workflow_config import *  # noqa: F403
from ksi_core.domains.external.authority.external_result_workflow_config import (
    _open_protected_authority_journal as _open_protected_authority_journal,
)
from ksi_core.domains.external.authority.external_result_workflow_config import (
    _validate_authority_journal_bundle as _validate_authority_journal_bundle,
)

_sys.modules[__name__] = _canonical
