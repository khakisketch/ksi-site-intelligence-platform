"""Replay gates for two-stage external quantitative authority."""

import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from ksi_core.auth import Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_quantitative_authority import (
    ExternalQuantitativeAuthorityCatalog,
    ExternalQuantitativeAuthorityRecoveryError,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalPairUseDecisionV1,
)

_CONTRACT_TESTS = Path(__file__).resolve().parents[1] / "contract"
sys.path.insert(0, str(_CONTRACT_TESTS))

from test_external_quantitative_authority import (  # noqa: E402
    _NOW,
    _digest,
    _mapping,
    _template,
)


def _decision(mapping):
    return {
        "decisionId": "decision-a",
        "decisionDigest": _digest("decision-a"),
        "organizationId": mapping.organization_id,
        "siteId": mapping.site_id,
        "baseline": mapping.baseline.subject,
        "current": mapping.current.subject,
        "zoneDigest": mapping.zone_snapshot.definition_digest,
        "policyDigest": mapping.validation_policy_digest,
        "compatibilityMappingDigest": mapping.mapping_digest,
        "decisionUse": "RELATIVE_VOLUME",
        "decisionVerdict": "ELIGIBLE",
        "decidedAt": _NOW,
    }


def _eligible_decision(mapping, *, decided_at):
    return ExternalPairUseDecisionV1(
        decision_id="decision-a",
        baseline_subject=mapping.baseline.subject,
        baseline_subject_digest=mapping.baseline.subject.canonical_digest(),
        current_subject=mapping.current.subject,
        current_subject_digest=mapping.current.subject.canonical_digest(),
        use="RELATIVE_VOLUME",
        policy_digest=mapping.validation_policy_digest,
        baseline_inspection_report_digest=mapping.baseline.inspection_report_digest,
        current_inspection_report_digest=mapping.current.inspection_report_digest,
        evidence_record_digests=mapping.evidence_record_digests,
        zone=mapping.zone_snapshot.to_zone_reference(),
        compatibility_mapping_digest=mapping.mapping_digest,
        verdict=DecisionVerdict.ELIGIBLE,
        reasons=("USE_ELIGIBLE",),
        remediations=("CURRENT_DEPENDENCIES_RETAINED",),
        decided_at=decided_at,
    ).sealed()


def _event_digest(event: dict[str, object]) -> str:
    payload = {key: value for key, value in event.items() if key != "eventDigest"}
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def test_restart_rejects_execution_snapshot_without_its_durable_decision(tmp_path: Path):
    """Dropping a decision journal must not let a retained execution snapshot replay."""
    path = tmp_path / "quantitative-authority.jsonl"
    mapping = _mapping()
    principal = Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
        execution_template_resolver=lambda _record, _now: _template(),
    )
    catalog.admit_mapping(mapping, actor="authority-a", now=_NOW)
    catalog.bind_decision_resolver(lambda *_args: _decision(mapping))
    assert (
        catalog.activate_execution(
            decision_ref="decision-a",
            principal=principal,
            current_work_order_id="work-current",
            now=_NOW,
        )
        is not None
    )
    catalog._journal.close()

    recovered = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )

    class _MissingDecisionStore:
        def resolve_current_pair_for_issue(self, *_args, **_kwargs):
            return None

        def resolve_historical_pair(self, **_kwargs):
            return None

    with pytest.raises(ExternalQuantitativeAuthorityRecoveryError, match="decision"):
        recovered.bind_decision_store(_MissingDecisionStore())
    recovered._journal.close()


def test_restart_rejects_test_corrupted_activation_before_exact_decision(tmp_path: Path) -> None:
    """Replay independently rejects a journal chronology contradiction."""
    path = tmp_path / "quantitative-authority.jsonl"
    mapping = _mapping()
    decision = _eligible_decision(mapping, decided_at=_NOW + timedelta(minutes=1))
    principal = Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")
    catalog = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path),
        currentness_coordinator=ExternalAuthorityCurrentnessCoordinator(),
        mapping_admission_validator=lambda _record, _now: True,
        execution_template_resolver=lambda _record, _now: _template(),
    )
    assert catalog.admit_mapping(mapping, actor="authority-a", now=_NOW) is not None
    catalog.bind_decision_resolver(lambda *_args: decision)
    assert (
        catalog.activate_execution(
            decision_ref=decision.decision_id,
            principal=principal,
            current_work_order_id="work-current",
            now=decision.decided_at,
        )
        is not None
    )
    catalog._journal.close()

    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    activation = next(
        event for event in events if event["kind"] == "external-quantitative-execution-activated"
    )
    activation["activatedAt"] = _NOW.isoformat().replace("+00:00", "Z")
    activation["eventDigest"] = _event_digest(activation)
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )

    recovered = ExternalQuantitativeAuthorityCatalog(
        DurableJournal(path), currentness_coordinator=ExternalAuthorityCurrentnessCoordinator()
    )

    class _DecisionStore:
        def resolve_current_pair_for_issue(self, *_args, **_kwargs):
            return decision

        def resolve_historical_pair(self, **_kwargs):
            return decision

    with pytest.raises(ExternalQuantitativeAuthorityRecoveryError, match="decision"):
        recovered.bind_decision_store(_DecisionStore())
    recovered._journal.close()
