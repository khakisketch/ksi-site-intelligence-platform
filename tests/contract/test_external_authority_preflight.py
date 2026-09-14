"""The candidate authority preflight validates configuration without activation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ksi_core.external_relative_volume_s3_capabilities import (
    ExternalRelativeVolumeS3InputCapabilityIssuer,
)


def test_preflight_rejects_a_workflow_path_outside_the_fixed_operator_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutable environment value cannot redirect the authority configuration read."""
    from ksi_core.external_authority_preflight import (
        ExternalAuthorityPreflightError,
        preflight_external_authority,
    )

    monkeypatch.setenv(
        "KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG", "/tmp/other-project/workflow.json"
    )
    monkeypatch.setenv(
        "KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG", "/run/ksi-operator/provider.json"
    )

    with pytest.raises(ExternalAuthorityPreflightError, match="fixed operator mount"):
        preflight_external_authority()


def test_preflight_accepts_only_the_fixed_disposable_durable_authority_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The validation-only journal is fixed under Core's disposable data mount."""
    import ksi_core.external_authority_preflight as preflight

    operator_root = tmp_path / "operator"
    operator_root.mkdir()
    workflow_path = operator_root / "workflow.json"
    provider_path = operator_root / "provider.json"
    durable_journal = tmp_path / "data" / "external-quantitative-authority.jsonl"
    durable_journal.parent.mkdir()
    durable_journal.write_text("", encoding="utf-8")
    durable_journal.with_suffix(".jsonl.lock").write_text("", encoding="utf-8")
    workflow_path.write_text(
        json.dumps(
            {
                "version": "external-result-workflow-config.v1",
                "authorityJournalPath": str(durable_journal),
                "catalogPath": str(operator_root / "catalog.json"),
            }
        ),
        encoding="utf-8",
    )
    workflow_path.chmod(0o600)
    provider_path.write_text("{}", encoding="utf-8")

    class Provider:
        organization_id = "org-candidate"
        participants = object()

        @staticmethod
        def status() -> dict[str, object]:
            return {
                "status": "CONFIG_VALIDATED",
                "organizationId": "org-candidate",
                "businessEligible": False,
            }

    class Workflow:
        build_input_capability_issuer = ExternalRelativeVolumeS3InputCapabilityIssuer

    monkeypatch.setattr(preflight, "_OPERATOR_ROOT", operator_root)
    monkeypatch.setattr(preflight, "_WORKFLOW_CONFIG", workflow_path)
    monkeypatch.setattr(preflight, "_PROVIDER_CONFIG", provider_path)
    monkeypatch.setattr(preflight, "_AUTHORITY_JOURNAL_PATH", durable_journal)
    monkeypatch.setattr(preflight, "_require_readable_material", lambda _path: None)
    monkeypatch.setattr(preflight, "_load_provider", Provider)
    monkeypatch.setattr(
        preflight,
        "load_external_result_workflow_config",
        lambda *_args, **_kwargs: Workflow(),
    )
    monkeypatch.setenv("KSI_CORE_EXTERNAL_RESULT_WORKFLOW_CONFIG", str(workflow_path))
    monkeypatch.setenv("KSI_CORE_EXTERNAL_AUTHORITY_PROVIDER_CONFIG", str(provider_path))

    assert preflight.preflight_external_authority() == {
        "status": "CONFIG_VALIDATED",
        "organizationId": "org-candidate",
        "activationStatus": "NOT_ATTACHED",
        "quantitativeEligible": False,
    }

    workflow_path.write_text(
        json.dumps(
            {
                "version": "external-result-workflow-config.v1",
                "authorityJournalPath": "/tmp/authority.jsonl",
                "catalogPath": str(operator_root / "catalog.json"),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(preflight.ExternalAuthorityPreflightError, match="fixed durable data path"):
        preflight.preflight_external_authority()
