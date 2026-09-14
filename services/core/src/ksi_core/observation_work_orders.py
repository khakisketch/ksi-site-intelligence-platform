"""Legacy module alias for :mod:`ksi_core.domains.sites.observation_work_orders`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.sites import observation_work_orders as _canonical
from ksi_core.domains.sites.observation_work_orders import *  # noqa: F403
from ksi_core.domains.sites.observation_work_orders import (
    ExternalReconstructionExecutionDenied as ExternalReconstructionExecutionDenied,
)
from ksi_core.domains.sites.observation_work_orders import (
    ExternalReobservationApprovalResult as ExternalReobservationApprovalResult,
)
from ksi_core.domains.sites.observation_work_orders import (
    ExternalReobservationExecutionDenied as ExternalReobservationExecutionDenied,
)
from ksi_core.domains.sites.observation_work_orders import (
    ExternalReobservationProposalAuthorityPort as ExternalReobservationProposalAuthorityPort,
)
from ksi_core.domains.sites.observation_work_orders import (
    ObservationWorkOrder as ObservationWorkOrder,
)
from ksi_core.domains.sites.observation_work_orders import (
    WorkOrderOperationsAssignmentAction as WorkOrderOperationsAssignmentAction,
)
from ksi_core.domains.sites.observation_work_orders import (
    build_observation_work_order_router as build_observation_work_order_router,
)

_sys.modules[__name__] = _canonical
