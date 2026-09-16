"""Legacy module alias for :mod:`ksi_core.domains.processing.processing_jobs`."""
from __future__ import annotations

import sys as _sys

from ksi_core.domains.processing import processing_jobs as _canonical
from ksi_core.domains.processing.processing_jobs import *  # noqa: F403
from ksi_core.domains.processing.processing_jobs import (
    _TRANSITION_PERMISSION as _TRANSITION_PERMISSION,
)
from ksi_core.domains.processing.processing_jobs import (
    ProcessingJobStatus as ProcessingJobStatus,
)
from ksi_core.domains.processing.processing_jobs import (
    build_processing_artifact_object_key as build_processing_artifact_object_key,
)

_sys.modules[__name__] = _canonical
