"""In-process serialization for external authority mutation and current-use checks.

The coordinator is deliberately process-local: a deployment that has more than
one durable-journal writer still needs a shared transactional lock.  It keeps
the final currentness check and a following local journal append indivisible
from relevant Core mutations without holding the lock during storage or remote
authority I/O.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock


class ExternalAuthorityCurrentnessCoordinator:
    """Shared re-entrant lock for external authority participants.

    Stores acquire this lock before their own journal/projection lock for a
    mutation.  A use evaluator keeps ``guarded_read`` open only while resolving
    local current authority and appending its decision; ordinary reads do not
    acquire it.
    """

    def __init__(self) -> None:
        self._lock = RLock()

    @contextmanager
    def mutation(self) -> Iterator[None]:
        with self._lock:
            yield

    @contextmanager
    def guarded_read(self) -> Iterator[None]:
        with self._lock:
            yield


__all__ = ["ExternalAuthorityCurrentnessCoordinator"]
