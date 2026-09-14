"""Legacy module alias."""

from __future__ import annotations

import sys as _sys

from ksi_core.composition import production as _canonical
from ksi_core.composition.production import *  # noqa: F403
from ksi_core.composition.production import (
    _acquisition_coordination_env as _acquisition_coordination_env,
)
from ksi_core.composition.production import (
    _acquisition_issue_gate_env as _acquisition_issue_gate_env,
)
from ksi_core.composition.production import (
    _checkpoint_validation_registration_env as _checkpoint_validation_registration_env,
)
from ksi_core.composition.production import (
    _copilot_runtime_config_env as _copilot_runtime_config_env,
)
from ksi_core.composition.production import (
    _external_authority_paths_env as _external_authority_paths_env,
)
from ksi_core.composition.production import _human_auth_config_env as _human_auth_config_env
from ksi_core.composition.production import (
    _optional_capability_freshness_policies as _optional_capability_freshness_policies,
)
from ksi_core.composition.production import (
    _optional_runtime_route_configurations as _optional_runtime_route_configurations,
)
from ksi_core.composition.production import build_production_app as build_production_app
from ksi_core.composition.production import datetime as datetime

_sys.modules[__name__] = _canonical
