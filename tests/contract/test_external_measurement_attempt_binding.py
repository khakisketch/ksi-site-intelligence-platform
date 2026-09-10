"""V2 attempt identity cannot be confused with the inspection parser or namespace."""

from __future__ import annotations

from dataclasses import replace

import pytest
from ksi_processing_controller.external_inspector_attempts import (
    AttemptBindingV1,
    AttemptJournalError,
    PrivateStagingRootV1,
)
from ksi_processing_controller.external_measurement_attempts import (
    MeasurementAttemptBindingV2,
    new_measurement_attempt_binding,
)
from test_external_measurement_protocol import measurement_manifest_request


def binding():
    manifest, request = measurement_manifest_request()
    return new_measurement_attempt_binding(
        request=request,
        manifest=manifest,
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        systemd_base_slice="ksi-inspector.slice",
        cpu_budget_counter=1_000_000,
        allocation_nonce="fixture-allocation-1",
    )


def test_exact_v2_binding_roundtrip_separates_execution_from_v1_parser() -> None:
    value = binding()
    assert MeasurementAttemptBindingV2.from_wire(value.wire()) == value
    assert value.algorithm_build_digest == value.execution_manifest_digest
    assert "parserBuildDigest" not in value.wire()
    assert value.runtime_description == "ksi-external-measurement-attempt.v2:" + value.digest
    assert value.container_name.startswith("external-measurement-")
    assert value.staging.staging_name.startswith("measurement-")
    with pytest.raises(AttemptJournalError):
        AttemptBindingV1.from_wire(value.wire())


@pytest.mark.parametrize(
    "mutation", ["algorithm", "operation", "parser", "primary", "secondary", "namespace"]
)
def test_binding_rejects_semantic_substitution(mutation: str) -> None:
    value = binding()
    wire = value.wire()
    if mutation == "algorithm":
        wire["algorithmBuildDigest"] = "sha256:" + "0" * 64
    elif mutation == "operation":
        wire["operation"] = "INSPECT"
    elif mutation == "parser":
        wire["parserBuildDigest"] = wire.pop("algorithmBuildDigest")
    elif mutation == "primary":
        wire["primaryInput"], wire["secondaryInput"] = wire["secondaryInput"], wire["primaryInput"]
    elif mutation == "secondary":
        wire["secondaryInput"]["observedSizeBytes"] = 0
    elif mutation == "namespace":
        wire["containerName"] = "external-inspector-fixture"
    with pytest.raises((AttemptJournalError, ValueError)):
        MeasurementAttemptBindingV2.from_wire(wire)


def test_v2_binding_digest_covers_declared_secondary() -> None:
    value = binding()
    changed = replace(
        value,
        secondary_input=value.secondary_input.model_copy(
            update={"observed_sha256": "sha256:" + "0" * 64}
        ),
    )
    assert changed.digest != value.digest
