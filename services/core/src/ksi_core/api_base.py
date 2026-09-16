"""Legacy module alias for :mod:`ksi_core.foundation.api_base`."""

from __future__ import annotations

import sys as _sys

from ksi_core.foundation import api_base as _canonical
from ksi_core.foundation.api_base import *  # noqa: F403
from ksi_core.foundation.api_base import _render_safe  # noqa: F401

_sys.modules[__name__] = _canonical
