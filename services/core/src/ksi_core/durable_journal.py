"""Legacy module alias for :mod:`ksi_core.foundation.durable_journal`."""

from __future__ import annotations

import sys as _sys

from ksi_core.foundation import durable_journal as _canonical
from ksi_core.foundation.durable_journal import *  # noqa: F403
from ksi_core.foundation.durable_journal import (  # noqa: F401
    _WRITE,
    _acquire_writer_lock,
    _fsync_dir,
)

_sys.modules[__name__] = _canonical
