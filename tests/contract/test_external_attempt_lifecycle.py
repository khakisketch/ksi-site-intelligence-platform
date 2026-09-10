"""Ambiguous runtime creation cannot keep admission open after retention failure."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from ksi_processing_controller.external_attempt_lifecycle import (
    AttemptLifecycleRuntimePort,
    reconcile_inflight_creation,
)
from test_external_measurement_attempt_binding import binding


@pytest.mark.parametrize("journal_fails", [False, True])
def test_retention_failure_always_closes_admission(journal_fails: bool) -> None:
    latched: list[bool] = []

    def journal_append(*args: object, **kwargs: object) -> None:
        del args, kwargs
        if journal_fails:
            raise OSError("synthetic journal failure")

    def retain() -> None:
        raise OSError("synthetic retention failure")

    journal = SimpleNamespace(cleanup_required=journal_append, cleanup_failed=journal_append)
    parent = SimpleNamespace(adopt_if_prebound=lambda **kw: None)
    with pytest.raises(OSError, match="retention"):
        reconcile_inflight_creation(
            attempt=binding(),
            journal=journal,
            runtime_parent_port=parent,
            runtime_cleanup=cast(AttemptLifecycleRuntimePort[Any], object()),
            latch_admission_closed=lambda: latched.append(True),
            retain_for_recovery=retain,
            runtime_id=None,
            runtime_parent=None,
            parent_creating=True,
            container_creating=False,
        )
    assert latched == [True]
