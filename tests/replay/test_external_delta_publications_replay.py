"""Replay tests for the Core delta-publication lane (synthetic fixtures only).

Proves journal append/replay equality across restart, and that malformed,
cross-scope, version-spoofed or digest-tampered replays fail closed instead
of repairing.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ksi_core.domains.external.quantity.external_delta_publications import (
    DeltaOutputObservation,
    DeltaPublicationDispositionV1,
    DeltaPublicationPolicy,
    DeltaPublicationRecoveryError,
    DeltaSourceWitness,
    ExternalDeltaPublicationStore,
    FilesystemDeltaByteStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_domain.canonical_json import canonical_json_bytes

NOW = datetime(2026, 10, 26, tzinfo=UTC)
GRID_ROWS = 4
GRID_COLUMNS = 4
TRANSFORM = (1.0, 0.0, 100.0, 0.0, -1.0, 200.0)
BOUNDS = (100.0, 196.0, 104.0, 200.0)
V2_CONTRACT = "external-relative-volume-calculation-report.v2"
V3_CONTRACT = "external-masked-volume-calculation-identity.v3"


def _digest(marker: str) -> str:
    return "sha256:" + hashlib.sha256(marker.encode()).hexdigest()


def _transform_digest() -> str:
    return (
        "sha256:" + hashlib.sha256(canonical_json_bytes({"transform": list(TRANSFORM)})).hexdigest()
    )


CALC_DIGEST = _digest("calculation")
NUMERIC_DIGEST = _digest("numeric")
COVERAGE_DIGEST = _digest("coverage")
CRS_DIGEST = _digest("horizontal-crs")


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _operator(org: str = "org-a") -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, org)


def _worker(org: str = "org-a", principal_id: str = "analysis-worker-1") -> Principal:
    return Principal(principal_id, PrincipalKind.ANALYSIS_WORKER, None, None, org)


class _FakeSource:
    def __init__(self, version: str = V3_CONTRACT) -> None:
        self.version = version
        self.live = True

    def resolve_current_source(self, **kwargs):  # type: ignore[no-untyped-def]
        if not self.live:
            return None
        return DeltaSourceWitness(
            organization_id=kwargs["organization_id"],
            site_id=kwargs["site_id"],
            work_area_id=kwargs["work_area_id"],
            source_contract_version=self.version,  # type: ignore[arg-type]
            source_calculation_identity_digest=kwargs["source_calculation_identity_digest"],
            source_numeric_result_identity_digest=kwargs["source_numeric_result_identity_digest"],
            source_coverage_witness_digest=kwargs["source_coverage_witness_digest"],
            grid_rows=GRID_ROWS,
            grid_columns=GRID_COLUMNS,
            transform=TRANSFORM,
            transform_digest=_transform_digest(),
            grid_crs_identifier="EPSG:5186",
            grid_crs_digest=CRS_DIGEST,
            bounds=BOUNDS,
        )


class _FakeAuthority:
    def __init__(self) -> None:
        self.policy_current = True
        self.runtime_current = True

    def is_policy_current(self, *, policy_digest: str, now: datetime) -> bool:
        return self.policy_current

    def is_runtime_current(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.runtime_current


class _FakeEgress:
    def is_egress_allowed(self, **kwargs):  # type: ignore[no-untyped-def]
        return True


class _FakeObservations:
    def __init__(self) -> None:
        self._bound = {}

    def bind(self, observation) -> None:  # type: ignore[no-untyped-def]
        self._bound[
            (
                observation.publication_id,
                observation.worker_principal_id,
                observation.worker_instance_id,
                observation.lease_generation,
            )
        ] = observation

    def resolve_output_observation(self, **kwargs):  # type: ignore[no-untyped-def]
        return self._bound.get(
            (
                kwargs["publication_id"],
                kwargs["worker_principal_id"],
                kwargs["worker_instance_id"],
                kwargs["lease_generation"],
            )
        )


def _policy() -> DeltaPublicationPolicy:
    return DeltaPublicationPolicy(
        policy_id="delta-publication-test-v1",
        version=1,
        max_output_bytes=1_000_000,
        max_grid_cells=1_000_000,
        max_lifetime_seconds=86_400,
        max_active_publications=8,
        upload_lease_duration_seconds=600,
        max_upload_attempts=8,
    )


def _open(tmp_path: Path, source=None, authority=None, clock=None, observations=None, policy=None):  # type: ignore[no-untyped-def]
    fake_observations = observations or _FakeObservations()
    store = ExternalDeltaPublicationStore(
        DurableJournal(tmp_path / "delta-publications.jsonl"),
        source_witness=source or _FakeSource(),
        authority=authority or _FakeAuthority(),
        egress=_FakeEgress(),
        byte_store=FilesystemDeltaByteStore(tmp_path / "delta-bytes"),
        observations=fake_observations,
        policy=policy or _policy(),
        clock=clock or _Clock(),
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    return store, fake_observations


def _intent_kwargs(**overrides):  # type: ignore[no-untyped-def]
    fields = {
        "publication_id": "pub-01",
        "site_id": "site-a",
        "work_area_id": "work-area-a",
        "source_calculation_identity_digest": CALC_DIGEST,
        "source_numeric_result_identity_digest": NUMERIC_DIGEST,
        "source_coverage_witness_digest": COVERAGE_DIGEST,
        "grid_rows": GRID_ROWS,
        "grid_columns": GRID_COLUMNS,
        "transform": TRANSFORM,
        "transform_digest": _transform_digest(),
        "grid_crs_identifier": "EPSG:5186",
        "grid_crs_digest": CRS_DIGEST,
        "bounds": BOUNDS,
        "lifetime_seconds": 3_600,
        "now": NOW,
    }
    fields.update(overrides)
    return fields


def _sub(tmp_path, name):  # type: ignore[no-untyped-def]
    """Owner-private 0700 test subdir: the byte-root gate rejects lax ancestors."""
    path = tmp_path / name
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _payload(size: int = 1_024) -> bytes:
    return bytes(i % 256 for i in range(size))


def _observation(payload: bytes):  # type: ignore[no-untyped-def]
    return DeltaOutputObservation(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_contract_version=V3_CONTRACT,
        source_calculation_identity_digest=CALC_DIGEST,
        source_numeric_result_identity_digest=NUMERIC_DIGEST,
        source_coverage_witness_digest=COVERAGE_DIGEST,
        publication_id="pub-01",
        worker_principal_id="analysis-worker-1",
        worker_instance_id="inst-1",
        lease_generation=1,
        output_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        output_size_bytes=len(payload),
        grid_rows=GRID_ROWS,
        grid_columns=GRID_COLUMNS,
        transform=TRANSFORM,
        transform_digest=_transform_digest(),
        grid_crs_identifier="EPSG:5186",
        grid_crs_digest=CRS_DIGEST,
        bounds=BOUNDS,
        dtype="FLOAT64",
        delta_sign="CURRENT_MINUS_BASELINE",
        nodata_value="NAN",
    ).sealed()


def _published_state(tmp_path: Path) -> None:
    store, observations = _open(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = store.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-1",
        now=NOW,
    )
    assert lease is not None
    payload = _payload()
    observations.bind(_observation(payload))
    store.publish_output(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_generation=lease.lease_generation,
        byte_stream=io.BytesIO(payload),
    )
    store._journal.close()  # noqa: SLF001 - simulate a crash after requested fsync


def _records(path: Path) -> list:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write(path: Path, records: list) -> None:
    path.write_text("".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records))


def _reseal(event: dict) -> None:
    payload = {key: value for key, value in event.items() if key != "eventDigest"}
    event["eventDigest"] = "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def test_restart_replays_exact_history_with_unchanged_journal_bytes(tmp_path: Path) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    before = journal_path.read_bytes()
    store, _ = _open(tmp_path)
    view, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.AVAILABLE and view is not None
    assert view.descriptor.output_size_bytes == 1_024
    assert view.descriptor.source_contract_version == V3_CONTRACT
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=16) == _payload()[:16]
    assert journal_path.read_bytes() == before


def test_restart_after_revocation_keeps_terminal_state_and_bytes_blocked(tmp_path: Path) -> None:
    _published_state(tmp_path)
    store, _ = _open(tmp_path)
    store.revoke(principal=_operator(), publication_id="pub-01", reason="SUPERSEDED", now=NOW)
    store._journal.close()  # noqa: SLF001
    journal_path = tmp_path / "delta-publications.jsonl"
    before = journal_path.read_bytes()
    reopened, _ = _open(tmp_path)
    view, disposition = reopened.get_current_with_disposition(
        "pub-01", principal=_operator(), now=NOW
    )
    assert view is None and disposition is DeltaPublicationDispositionV1.REVOKED
    assert reopened.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    assert journal_path.read_bytes() == before


def test_restart_after_corrupt_tail_still_recovers_completed_tail(tmp_path: Path) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    with open(journal_path, "ab") as handle:
        handle.write(b'{"kind": "torn-tail')
    store, _ = _open(tmp_path)
    view, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.AVAILABLE and view is not None


@pytest.mark.parametrize(
    "tamper", ["digest", "shape", "cross-scope", "reordered", "bool-version", "unknown-kind"]
)
def test_replay_rejects_tampered_journals_without_repair(tmp_path: Path, tamper: str) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    if tamper == "digest":
        records[0]["siteId"] = "site-tampered"
    elif tamper == "shape":
        records[2]["unexpected"] = "value"
        _reseal(records[2])
    elif tamper == "cross-scope":
        records[2]["organizationId"] = "org-b"
        _reseal(records[2])
    elif tamper == "reordered":
        records = [records[2], records[1], records[0]]
    elif tamper == "bool-version":
        records[1]["version"] = True
    else:
        records.append(
            {"kind": "delta-publication-unknown", "version": 1, "eventDigest": _digest("unknown")}
        )
        _reseal(records[-1])
    _write(journal_path, records)
    journal = DurableJournal(journal_path)
    with pytest.raises(DeltaPublicationRecoveryError):
        ExternalDeltaPublicationStore(
            journal,
            source_witness=_FakeSource(),
            authority=_FakeAuthority(),
            egress=_FakeEgress(),
            byte_store=FilesystemDeltaByteStore(tmp_path / "delta-bytes"),
            observations=_FakeObservations(),
            policy=_policy(),
            clock=_Clock(),
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )
    assert journal.sealed_reason == "closed"


def test_replay_rejects_spoofed_source_contract_version(tmp_path: Path) -> None:
    """A V2 descriptor journaled against a V3 intent (or vice versa) must not replay."""
    from ksi_event_contracts.external_masked_volume import DeltaRasterPublicationV1

    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    sealed_v2 = (
        DeltaRasterPublicationV1.model_validate(published["descriptor"])
        .model_copy(update={"source_contract_version": V2_CONTRACT, "publication_digest": None})
        .sealed()
    )
    published["descriptor"] = sealed_v2.model_dump(by_alias=True, mode="json")
    _reseal(published)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)


def test_replay_rejects_descriptor_digest_tamper_even_if_resealed(tmp_path: Path) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    published["descriptor"]["outputSha256"] = _digest("other-output-bytes")
    _reseal(published)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)


def test_replay_rejects_lease_generation_skip_and_holder_swap(tmp_path: Path) -> None:
    _published_state(_sub(tmp_path, "skip"))
    journal_path = _sub(tmp_path, "skip") / "delta-publications.jsonl"
    records = _records(journal_path)
    leased = next(r for r in records if r["kind"] == "delta-publication-upload-leased")
    leased["leaseGeneration"] = 7
    _reseal(leased)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(_sub(tmp_path, "skip"))

    _published_state(_sub(tmp_path, "swap"))
    journal_path = _sub(tmp_path, "swap") / "delta-publications.jsonl"
    records = _records(journal_path)
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    published["holderPrincipalId"] = "analysis-worker-2"
    _reseal(published)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(_sub(tmp_path, "swap"))


def test_replay_rejects_spent_acquisition_reuse_and_duration_violation(
    tmp_path: Path,
) -> None:
    _published_state(_sub(tmp_path, "reuse"))
    journal_path = _sub(tmp_path, "reuse") / "delta-publications.jsonl"
    records = _records(journal_path)
    leased = next(r for r in records if r["kind"] == "delta-publication-upload-leased")
    forged = dict(leased)
    forged["leaseGeneration"] = 2
    _reseal(forged)
    records.insert(2, forged)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(_sub(tmp_path, "reuse"))

    _published_state(_sub(tmp_path, "duration"))
    journal_path = _sub(tmp_path, "duration") / "delta-publications.jsonl"
    records = _records(journal_path)
    leased = next(r for r in records if r["kind"] == "delta-publication-upload-leased")
    leased["expiresAt"] = "2026-10-26T01:00:00+00:00"
    _reseal(leased)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(_sub(tmp_path, "duration"))


def test_replay_rejects_unknown_policy_binding(tmp_path: Path) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    records[0]["policyDigest"] = _digest("unknown-policy")
    _reseal(records[0])
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)


def test_missing_bytes_after_journal_replay_fail_closed_on_read(tmp_path: Path) -> None:
    _published_state(tmp_path)
    for child in (tmp_path / "delta-bytes").glob("*.tiff"):
        child.unlink()
    store, _ = _open(tmp_path)
    view, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert view is None and disposition is DeltaPublicationDispositionV1.BYTES_UNAVAILABLE
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None


def test_truncated_bytes_after_journal_replay_fail_closed_on_read(tmp_path: Path) -> None:
    _published_state(tmp_path)
    target = tmp_path / "delta-bytes" / "delta-out-pub-01.tiff"
    target.write_bytes(target.read_bytes()[:512])
    store, _ = _open(tmp_path)
    view, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert view is None and disposition is DeltaPublicationDispositionV1.BYTES_UNAVAILABLE
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None


def test_revocation_only_applies_to_published_records_on_replay(tmp_path: Path) -> None:
    store, _ = _open(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-pending"))
    store._journal.close()  # noqa: SLF001
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    forged = {
        "kind": "delta-publication-revoked",
        "version": 1,
        "organizationId": "org-a",
        "publicationId": "pub-pending",
        "reason": "FORGED",
        "revokedAt": NOW.isoformat(),
    }
    _reseal(forged)
    records.append(forged)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)


def test_replay_rejects_observation_binding_mismatch(tmp_path: Path) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"

    records = _records(journal_path)
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    published["observation"]["outputSha256"] = _digest("other-output-bytes")
    _reseal(published)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)

    _published_state(_sub(tmp_path, "shape"))
    journal_path = _sub(tmp_path, "shape") / "delta-publications.jsonl"
    records = _records(journal_path)
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    del published["observationDigest"]
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(_sub(tmp_path, "shape"))

    _published_state(_sub(tmp_path, "grid"))
    journal_path = _sub(tmp_path, "grid") / "delta-publications.jsonl"
    records = _records(journal_path)
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    published["observation"]["gridRows"] = 8
    _reseal(published)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(_sub(tmp_path, "grid"))


def test_replay_rejects_observation_version_and_holder_mismatch(tmp_path: Path) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    payload = _payload()
    v2_observation = DeltaOutputObservation(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_contract_version=V2_CONTRACT,
        source_calculation_identity_digest=CALC_DIGEST,
        source_numeric_result_identity_digest=NUMERIC_DIGEST,
        source_coverage_witness_digest=COVERAGE_DIGEST,
        publication_id="pub-01",
        worker_principal_id="analysis-worker-1",
        worker_instance_id="inst-1",
        lease_generation=1,
        output_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        output_size_bytes=len(payload),
        grid_rows=GRID_ROWS,
        grid_columns=GRID_COLUMNS,
        transform=TRANSFORM,
        transform_digest=_transform_digest(),
        grid_crs_identifier="EPSG:5186",
        grid_crs_digest=CRS_DIGEST,
        bounds=BOUNDS,
        dtype="FLOAT64",
        delta_sign="CURRENT_MINUS_BASELINE",
        nodata_value="NAN",
    ).sealed()
    published["observation"] = v2_observation.canonical_payload()
    published["observationDigest"] = v2_observation.canonical_digest()
    _reseal(published)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)

    _published_state(_sub(tmp_path, "holder"))
    journal_path = _sub(tmp_path, "holder") / "delta-publications.jsonl"
    records = _records(journal_path)
    published = next(r for r in records if r["kind"] == "delta-publication-published")
    published["observation"]["workerInstanceId"] = "inst-impostor"
    _reseal(published)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(_sub(tmp_path, "holder"))


def test_replay_accepts_truncated_lease_bound(tmp_path: Path) -> None:
    store, observations = _open(tmp_path)
    store.create_intent(
        principal=_operator(),
        **{**_intent_kwargs(), "publication_id": "pub-short", "lifetime_seconds": 30},
    )
    lease = store.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-short",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-short",
        now=NOW,
    )
    assert lease is not None
    assert lease.lease_expires_at == NOW + timedelta(seconds=30)
    store._journal.close()  # noqa: SLF001
    journal_path = tmp_path / "delta-publications.jsonl"
    before = journal_path.read_bytes()
    reopened, _ = _open(tmp_path)
    view, _ = reopened.get_current_with_disposition("pub-short", principal=_operator(), now=NOW)
    assert view is None
    retried = reopened.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-short",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-short",
        now=NOW,
    )
    assert retried is not None and retried.lease_generation == 1
    assert retried.lease_expires_at == NOW + timedelta(seconds=30)
    assert journal_path.read_bytes() == before


def test_replay_rejects_oversize_lease_expiry(tmp_path: Path) -> None:
    store, _ = _open(tmp_path)
    store.create_intent(
        principal=_operator(),
        **{**_intent_kwargs(), "publication_id": "pub-short", "lifetime_seconds": 30},
    )
    lease = store.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-short",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-short",
        now=NOW,
    )
    assert lease is not None
    store._journal.close()  # noqa: SLF001
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    leased = next(r for r in records if r["kind"] == "delta-publication-upload-leased")
    leased["expiresAt"] = "2026-10-26T00:10:00+00:00"
    _reseal(leased)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)


def test_replay_rejects_skipped_lease_generation(tmp_path: Path) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    leased = next(r for r in records if r["kind"] == "delta-publication-upload-leased")
    forged = dict(leased)
    forged["leaseGeneration"] = 3
    forged["leaseAcquisitionId"] = "acq-skipped"
    _reseal(forged)
    published_index = next(
        index
        for index, record in enumerate(records)
        if record["kind"] == "delta-publication-published"
    )
    records.insert(published_index, forged)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)


def test_replay_rejects_overcap_lease_generation(tmp_path: Path) -> None:
    _published_state(tmp_path)
    journal_path = tmp_path / "delta-publications.jsonl"
    records = _records(journal_path)
    leased = next(r for r in records if r["kind"] == "delta-publication-upload-leased")
    published_index = next(
        index
        for index, record in enumerate(records)
        if record["kind"] == "delta-publication-published"
    )
    for generation in range(2, 10):
        forged = dict(leased)
        forged["leaseGeneration"] = generation
        forged["leaseAcquisitionId"] = f"acq-{generation}"
        _reseal(forged)
        records.insert(published_index + generation - 2, forged)
    _write(journal_path, records)
    with pytest.raises(DeltaPublicationRecoveryError):
        _open(tmp_path)


def test_restart_lists_lapsed_lease_for_recovery(tmp_path: Path) -> None:
    clock = _Clock()
    store, _ = _open(tmp_path, clock=clock)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = store.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-1",
        now=clock.now,
    )
    assert lease is not None
    store._journal.close()  # noqa: SLF001
    journal_path = tmp_path / "delta-publications.jsonl"
    before = journal_path.read_bytes()
    late = _Clock(NOW + timedelta(seconds=601))
    reopened, _ = _open(tmp_path, clock=late)
    assert reopened.list_pending_for_worker(worker_principal=_worker()) == ("pub-01",)
    retaken = reopened.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-2",
        now=late.now,
    )
    assert retaken is not None and retaken.lease_generation == 2
    assert journal_path.read_bytes() != before
    journal_len = len(_records(journal_path))
    same = reopened.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-2",
        now=late.now,
    )
    assert same is not None and same.lease_generation == 2
    assert len(_records(journal_path)) == journal_len


def test_restart_hides_cap_exhausted_intent(tmp_path: Path) -> None:
    capped = DeltaPublicationPolicy(
        policy_id="delta-publication-test-v1",
        version=1,
        max_output_bytes=1_000_000,
        max_grid_cells=1_000_000,
        max_lifetime_seconds=86_400,
        max_active_publications=8,
        upload_lease_duration_seconds=600,
        max_upload_attempts=1,
    )
    clock = _Clock()
    store, _ = _open(tmp_path, clock=clock, policy=capped)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = store.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-1",
        now=clock.now,
    )
    assert lease is not None
    store._journal.close()  # noqa: SLF001
    late = _Clock(NOW + timedelta(seconds=601))
    reopened, _ = _open(tmp_path, clock=late, policy=capped)
    assert reopened.list_pending_for_worker(worker_principal=_worker()) == ()
    assert (
        reopened.acquire_upload_lease(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_acquisition_id="acq-2",
            now=late.now,
        )
        is None
    )
