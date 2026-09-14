"""Legacy module alias for :mod:`ksi_core.foundation.observability`."""

from __future__ import annotations

import sys as _sys

from ksi_core.foundation import observability as _canonical
from ksi_core.foundation.observability import *  # noqa: F403
from ksi_core.foundation.observability import _CorrelationIdFilter  # noqa: F401

_sys.modules[__name__] = _canonical
