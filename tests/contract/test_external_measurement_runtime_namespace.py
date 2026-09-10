"""Fixed V1/V2 systemd selectors reject crossed authority before manager effects."""

from __future__ import annotations

from typing import Any, cast

import pytest
from ksi_processing_controller.external_inspector_systemd import (
    SystemdRuntimeUnavailable,
    SystemdTransientSliceConfigV1,
    SystemdTransientSliceController,
)
from ksi_processing_controller.external_measurement_attempts import MeasurementAttemptBindingV2
from ksi_processing_controller.external_measurement_systemd import (
    MeasurementSystemdTransientSliceController,
)
from test_external_inspector_docker import _binding
from test_external_measurement_attempt_binding import binding
from test_external_measurement_attempt_journal import parent_receipt


@pytest.mark.parametrize("v2_controller", [False, True])
def test_crossed_namespace_cannot_create_adopt_or_stop(v2_controller: bool) -> None:
    class NoManagerEffects:
        def __getattr__(self, name: str) -> object:
            raise AssertionError("cross-version manager access " + name)

    controller_type = (
        MeasurementSystemdTransientSliceController
        if v2_controller
        else SystemdTransientSliceController
    )
    controller = controller_type(
        manager=cast(Any, NoManagerEffects()),
        cgroups=cast(Any, None),
        runtime_lifecycle=cast(Any, None),
        proc_cgroups=cast(Any, None),
        config=SystemdTransientSliceConfigV1(
            base_slice_name="ksi-inspector.slice", stable_final_samples=2, cleanup_timeout_millis=10
        ),
    )
    value = _binding() if v2_controller else binding()
    with pytest.raises(SystemdRuntimeUnavailable, match="namespace"):
        controller.bind_before_create(binding=value, configuration=cast(Any, None))
    with pytest.raises(SystemdRuntimeUnavailable, match="namespace"):
        controller.adopt_if_prebound(binding=value)
    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    if v2_controller:
        wire = parent_receipt(cast(MeasurementAttemptBindingV2, binding())).wire()
        wire.update(unitName=value.systemd_slice_name, description=value.runtime_description)
        receipt = RuntimeParentReceiptV1.from_wire(wire)
    else:
        receipt = parent_receipt(cast(MeasurementAttemptBindingV2, value))
    assert controller.stop_exact(binding=value, receipt=receipt) is False
    assert (
        controller.verify_before_quiesce(binding=value, receipt=receipt, runtime_id="runtime")
        is False
    )
    assert (
        controller.verify_final_before_remove(binding=value, receipt=receipt, runtime_id="runtime")
        is False
    )
