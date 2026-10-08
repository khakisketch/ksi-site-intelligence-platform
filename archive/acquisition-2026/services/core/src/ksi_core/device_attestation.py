"""Legacy module alias for :mod:`ksi_core.identity.device_attestation`."""

from __future__ import annotations

import sys as _sys

from ksi_core.identity import device_attestation as _canonical
from ksi_core.identity.device_attestation import *  # noqa: F403

_sys.modules[__name__] = _canonical
