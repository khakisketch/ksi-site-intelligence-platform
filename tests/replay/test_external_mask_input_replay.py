"""Replay for the additive mask-child ingress journal (synthetic only)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
)
from ksi_core.domains.external.ingress.external_mask_input_store import (
    BaselineDsmAnchor,
    ExternalMaskInputStore,
    MaskInputRecoveryError,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_mask_input import (
    MaskChildDeclarationV1,
    MaskInspectionProfileV1,
)
from ksi_event_contracts.external_mask_input_report import (
    MaskObservationMeasurementsV1,
    MaskObservationReportV1,
)

NOW = datetime(2026, 10, 26, tzinfo=UTC)
TRANSFORM = (1.0, 0.0, 200000.0, 0.0, -1.0, 550000.0)
CRS_ID = "EPSG:5186"


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _subject(label: str) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="order-" + label,
        submission_id="submission-" + label,
        revision=1,
        submission_digest=_digest("submission-" + label),
        manifest_digest=_digest("manifest-" + label),
    )


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=4000000,
        max_streamed_bytes=4000000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1000000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20000000,
        max_sample_bytes=4000000,
        max_geometry_vertices=64,
        max_cpu_seconds=30.0,
        max_memory_bytes=50000000,
        max_workspace_bytes=50000000,
        max_output_bytes=1000000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


def _operator() -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")


def _designated_worker() -> Principal:
    return Principal("masked-worker-1", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a")


def _wrong_worker() -> Principal:
    return Principal("masked-worker-9", PrincipalKind.ANALYSIS_WORKER, None, None, "org-a")


def _profile(envelope: ResourceEnvelopeV1) -> MaskInspectionProfileV1:
    return MaskInspectionProfileV1(
        profile_id="KSI-MASK-INSPECTION-V1",
        version=1,
        contained_protocol="CONTAINED_MASK_INSPECTION_V1",
        runtime_image_version="9.9.9",
        runtime_image_oci_digest=_digest("oci"),
        worker_executable_digest=_digest("exe"),
        worker_build_digest=_digest("build"),
        dependency_lock_digest=_digest("lock"),
        mask_grammar_digest=_digest("mask-grammar-v1"),
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        resource_envelope_digest=envelope.canonical_digest(),
    ).sealed()


class _Authority:
    """Explicit test authority: current subjects + baseline anchor (synthetic, labelled)."""

    label = "synthetic-not-field"

    def __init__(self) -> None:
        self.live = True

    def is_subject_current(self, *, subject, organization_id, site_id, work_area_id, now):
        if not self.live:
            return False
        return subject in (_subject("parent"), _subject("baseline"))

    def fetch_baseline_anchor(
        self, *, organization_id, site_id, work_area_id, baseline_subject, dsm_artifact_id
    ):
        if not self.live or dsm_artifact_id != "dsm-baseline":
            return None
        if baseline_subject != _subject("baseline"):
            return None
        return BaselineDsmAnchor(
            baseline_subject_digest=_subject("baseline").canonical_digest(),
            dsm_artifact_id="dsm-baseline",
            rows=4,
            columns=4,
            observed_sha256=_digest("baseline-bytes"),
            observed_size_bytes=1024,
            transform=TRANSFORM,
            transform_digest=_canonical_digest({"transform": list(TRANSFORM)}),
            crs_identifier=CRS_ID,
            crs_digest=_digest("crs"),
        )


class _Activation:
    label = "synthetic-not-field"

    def __init__(self, profile: MaskInspectionProfileV1) -> None:
        self._digest = profile.canonical_digest()
        self.live = True

    def is_profile_active(
        self,
        *,
        profile_digest,
        resource_envelope_digest,
        contained_runtime_digest,
        inspector_build_digest,
        now,
    ):
        return self.live and profile_digest == self._digest


def _content() -> bytes:
    return bytes(i % 251 for i in range(128))


def _harness(tmp_path, observer: Principal | None = None):
    envelope = _envelope()
    profile = _profile(envelope)
    byte_store = ExternalMaskInputByteStore(
        DurableJournal(tmp_path / "mask-bytes.journal"),
        tmp_path / "mask-bytes",
        resource_envelope=envelope,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    authority = _Authority()
    activation = _Activation(profile)
    store = ExternalMaskInputStore(
        DurableJournal(tmp_path / "mask-child.journal"),
        resource_envelope=envelope,
        reconstruction_authority=authority,
        profile_activation=activation,
        sealed_bytes=byte_store,
        observer_principal=observer,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    return envelope, profile, byte_store, authority, activation, store


def _declare_and_seal(
    store, byte_store, profile, content: bytes, *, seal_principal: Principal | None = None
):
    import hashlib as _hl

    sha = "sha256:" + _hl.sha256(content).hexdigest()
    declaration = MaskChildDeclarationV1(
        declaration_id="decl-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        child_kind="MASK_CHILD",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
        parent_subject=_subject("parent"),
        target_baseline_subject=_subject("baseline"),
        target_baseline_dsm_artifact_id="dsm-baseline",
        declared_sha256=sha,
        declared_size_bytes=len(content),
    ).sealed()
    store.declare(principal=_operator(), declaration=declaration, now=NOW)
    grant = byte_store.issue_grant(
        principal=_operator(),
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
        subject_digest=_subject("parent").canonical_digest(),
        declared_sha256=sha,
        declared_size_bytes=len(content),
        now=NOW,
    )
    assert grant.object_key.startswith("mask/org-a/site-a/")
    byte_store.complete_upload(
        grant_id=grant.grant_id, data=content, principal=_operator(), now=NOW
    )
    measurements = MaskObservationMeasurementsV1(
        observed_crs_identifier=CRS_ID,
        observed_crs_digest=_digest("crs"),
        transform=TRANSFORM,
        transform_digest=_canonical_digest({"transform": list(TRANSFORM)}),
        width=4,
        height=4,
        band_count=1,
        dtype="UINT8",
        nodata_representation="NONE",
        bounds=(200000.0, 549996.0, 200004.0, 550000.0),
    )
    report = MaskObservationReportV1(
        report_id="report-1",
        mask_child_id="mask-child-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("parent"),
        subject_digest=_subject("parent").canonical_digest(),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=sha,
        observed_size_bytes=len(content),
        inspection_profile_digest=profile.canonical_digest(),
        contained_runtime_digest=_digest("contained-runtime"),
        inspector_build_digest=_digest("inspector-build"),
        measurements=measurements,
        reported_at=NOW,
    ).sealed()
    return store.seal_observed(
        principal=seal_principal or _operator(),
        organization_id="org-a",
        mask_child_id="mask-child-1",
        report=report,
        inspection_profile=profile,
        now=NOW,
    )


def test_declare_seal_get_replay_roundtrip(tmp_path) -> None:
    envelope, profile, byte_store, _, _, store = _harness(tmp_path)
    sealed = _declare_and_seal(store, byte_store, profile, _content())
    assert sealed.manifest_digest == sealed.canonical_digest()
    # Core-built manifest binds the declaration + narrow report, not caller rows.
    assert sealed.rows == 4 and sealed.columns == 4
    assert sealed.transform_digest == _canonical_digest({"transform": list(TRANSFORM)})
    assert sealed.observed_crs_identifier == CRS_ID
    record = store.get(
        organization_id="org-a",
        mask_child_id="mask-child-1",
        principal=_operator(),
        now=NOW,
    )
    assert record is not None and record.manifest is not None
    assert record.manifest.manifest_digest == sealed.manifest_digest
    # Returned records are deep copies: replacing the copy cannot corrupt history.
    replaced = record.manifest.model_copy(update={"rows": 99})
    assert replaced.rows == 99
    reread = store.get(
        organization_id="org-a",
        mask_child_id="mask-child-1",
        principal=_operator(),
        now=NOW,
    )
    assert reread is not None and reread.manifest is not None
    assert reread.manifest.rows == 4
    journal_path = tmp_path / "mask-child.journal"
    store._journal.close()  # noqa: SLF001
    byte_store._journal.close()  # noqa: SLF001
    replayed = ExternalMaskInputStore(
        DurableJournal(journal_path),
        resource_envelope=envelope,
        reconstruction_authority=_Authority(),
        profile_activation=_Activation(profile),
        sealed_bytes=byte_store,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    replayed_record = replayed.get(
        organization_id="org-a",
        mask_child_id="mask-child-1",
        principal=_operator(),
        now=NOW,
    )
    assert replayed_record is not None and replayed_record.manifest is not None
    assert replayed_record.manifest.manifest_digest == sealed.manifest_digest


def test_fabricated_subject_rejected_and_scope_area_checked(tmp_path) -> None:
    _, profile, byte_store, authority, _, store = _harness(tmp_path)
    _declare_and_seal(store, byte_store, profile, _content())
    authority.live = False
    forged = MaskChildDeclarationV1(
        declaration_id="decl-2",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        child_kind="MASK_CHILD",
        mask_child_id="mask-child-2",
        mask_artifact_id="mask-artifact-2",
        parent_subject=_subject("attacker"),
        target_baseline_subject=_subject("baseline"),
        target_baseline_dsm_artifact_id="dsm-baseline",
        declared_sha256=_digest("b"),
        declared_size_bytes=10,
    ).sealed()
    with pytest.raises(ValueError, match="not currently sealed"):
        store.declare(principal=_operator(), declaration=forged, now=NOW)
    # Uniform read: out-of-scope area sees None, not an exception/oracle.
    scoped = Principal(
        "mcp-1",
        PrincipalKind.ANALYSIS_MCP_CLIENT,
        None,
        None,
        "org-a",
        frozenset({"site-a"}),
        frozenset({"other-area"}),
        False,
        frozenset(),
    )
    got = store.get(
        organization_id="org-a",
        mask_child_id="mask-child-1",
        principal=scoped,
        now=NOW,
    )
    assert got is None
    store._journal.close()  # noqa: SLF001
    byte_store._journal.close()  # noqa: SLF001


def test_stale_report_or_inactive_profile_fails_closed(tmp_path) -> None:
    _, profile, byte_store, _, activation, store = _harness(tmp_path)
    _declare_and_seal(store, byte_store, profile, _content())
    activation.live = False
    report = MaskObservationReportV1(
        report_id="report-2",
        mask_child_id="mask-child-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("parent"),
        subject_digest=_subject("parent").canonical_digest(),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=_digest("mask-bytes"),
        observed_size_bytes=128,
        inspection_profile_digest=profile.canonical_digest(),
        contained_runtime_digest=_digest("contained-runtime"),
        inspector_build_digest=_digest("inspector-build"),
        measurements=MaskObservationMeasurementsV1(
            observed_crs_identifier=CRS_ID,
            observed_crs_digest=_digest("crs"),
            transform=TRANSFORM,
            transform_digest=_canonical_digest({"transform": list(TRANSFORM)}),
            width=4,
            height=4,
            band_count=1,
            dtype="UINT8",
            nodata_representation="NONE",
            bounds=(200000.0, 549996.0, 200004.0, 550000.0),
        ),
        reported_at=NOW,
    ).sealed()
    with pytest.raises(ValueError, match="not currently active|do not match"):
        store.seal_observed(
            principal=_operator(),
            organization_id="org-a",
            mask_child_id="mask-child-1",
            report=report,
            inspection_profile=profile,
            now=NOW,
        )
    store._journal.close()  # noqa: SLF001
    byte_store._journal.close()  # noqa: SLF001


def test_tampered_journal_fails_closed_on_replay(tmp_path) -> None:
    envelope, profile, byte_store, _, _, store = _harness(tmp_path)
    _declare_and_seal(store, byte_store, profile, _content())
    journal_path = tmp_path / "mask-child.journal"
    store._journal.close()  # noqa: SLF001
    byte_store._journal.close()  # noqa: SLF001
    lines = journal_path.read_text().splitlines()
    assert len(lines) == 2
    second = json.loads(lines[1])
    second["manifest"]["observedSizeBytes"] = 129
    lines[1] = json.dumps(second, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    journal_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(MaskInputRecoveryError):
        ExternalMaskInputStore(
            DurableJournal(journal_path),
            resource_envelope=envelope,
            reconstruction_authority=_Authority(),
            profile_activation=_Activation(profile),
            sealed_bytes=byte_store,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )


def test_replay_rejects_version_spoof_event_digest_tamper_and_unknown_kind(tmp_path) -> None:
    import json as _json

    from ksi_core.domains.external.ingress.external_mask_input_store import (
        MaskInputRecoveryError as _Recovery,
    )

    envelope, profile, byte_store, _, _, store = _harness(tmp_path)
    declaration = MaskChildDeclarationV1(
        declaration_id="decl-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        child_kind="MASK_CHILD",
        mask_child_id="mask-child-1",
        mask_artifact_id="mask-artifact-1",
        parent_subject=_subject("parent"),
        target_baseline_subject=_subject("baseline"),
        target_baseline_dsm_artifact_id="dsm-baseline",
        declared_sha256=_digest("mask-bytes-x"),
        declared_size_bytes=64,
    ).sealed()
    store.declare(principal=_operator(), declaration=declaration, now=NOW)
    journal_path = tmp_path / "mask-child.journal"
    store._journal.close()  # noqa: SLF001 - release lock before tampering the file
    byte_store._journal.close()  # noqa: SLF001
    lines = journal_path.read_text().splitlines()
    assert len(lines) == 1

    def _reopen(expect: str):
        with pytest.raises(_Recovery, match=expect):
            ExternalMaskInputStore(
                DurableJournal(journal_path),
                resource_envelope=envelope,
                reconstruction_authority=_Authority(),
                profile_activation=_Activation(profile),
                sealed_bytes=byte_store,
                coordinator=ExternalAuthorityCurrentnessCoordinator(),
            )

    tampered = _json.loads(lines[0])
    tampered["eventDigest"] = "sha256:" + "0" * 64
    journal_path.write_text(_json.dumps(tampered, ensure_ascii=True, separators=(",", ":")) + "\n")
    _reopen("digest is invalid")
    spoofed = _json.loads(lines[0])
    spoofed["version"] = True
    spoofed.pop("eventDigest", None)
    spoofed["eventDigest"] = _canonical_digest(
        {k: v for k, v in spoofed.items() if k != "eventDigest"}
    )
    journal_path.write_text(_json.dumps(spoofed, ensure_ascii=True, separators=(",", ":")) + "\n")
    _reopen("version is unsupported")
    unknown = _json.loads(lines[0])
    unknown["kind"] = "external-mask-child-unknown.v9"
    unknown.pop("eventDigest", None)
    unknown["eventDigest"] = _canonical_digest(
        {k: v for k, v in unknown.items() if k != "eventDigest"}
    )
    journal_path.write_text(_json.dumps(unknown, ensure_ascii=True, separators=(",", ":")) + "\n")
    _reopen("unknown mask-child journal kind")


def _narrow_report(profile: MaskInspectionProfileV1) -> MaskObservationReportV1:
    measurements = MaskObservationMeasurementsV1(
        observed_crs_identifier=CRS_ID,
        observed_crs_digest=_digest("crs"),
        transform=TRANSFORM,
        transform_digest=_canonical_digest({"transform": list(TRANSFORM)}),
        width=4,
        height=4,
        band_count=1,
        dtype="UINT8",
        nodata_representation="NONE",
        bounds=(200000.0, 549996.0, 200004.0, 550000.0),
    )
    return MaskObservationReportV1(
        report_id="report-1",
        mask_child_id="mask-child-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("parent"),
        subject_digest=_subject("parent").canonical_digest(),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=_digest("mask-bytes-x"),
        observed_size_bytes=64,
        inspection_profile_digest=profile.canonical_digest(),
        contained_runtime_digest=_digest("contained-runtime"),
        inspector_build_digest=_digest("inspector-build"),
        measurements=measurements,
        reported_at=NOW,
    ).sealed()


def test_worker_seal_with_pinned_observer(tmp_path) -> None:
    """The exact designated worker seals without SITES_WRITE; no grant is broadened."""
    _, profile, byte_store, _, _, store = _harness(tmp_path, observer=_designated_worker())
    sealed = _declare_and_seal(
        store, byte_store, profile, _content(), seal_principal=_designated_worker()
    )
    assert sealed.manifest_digest == sealed.canonical_digest()
    record = store.get(
        organization_id="org-a",
        mask_child_id="mask-child-1",
        principal=_operator(),
        now=NOW,
    )
    assert record is not None and record.manifest is not None
    store._journal.close()  # noqa: SLF001
    byte_store._journal.close()  # noqa: SLF001


def test_worker_seal_wrong_worker_denied(tmp_path) -> None:
    """Any other worker fails closed, even with the ANALYSIS_WORK permission."""
    _, profile, byte_store, _, _, store = _harness(tmp_path, observer=_designated_worker())
    store.declare(
        principal=_operator(),
        declaration=MaskChildDeclarationV1(
            declaration_id="decl-1",
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            child_kind="MASK_CHILD",
            mask_child_id="mask-child-1",
            mask_artifact_id="mask-artifact-1",
            parent_subject=_subject("parent"),
            target_baseline_subject=_subject("baseline"),
            target_baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest("mask-bytes-x"),
            declared_size_bytes=64,
        ).sealed(),
        now=NOW,
    )
    with pytest.raises(PermissionError):
        store.seal_observed(
            principal=_wrong_worker(),
            organization_id="org-a",
            mask_child_id="mask-child-1",
            report=_narrow_report(profile),
            inspection_profile=profile,
            now=NOW,
        )
    store._journal.close()  # noqa: SLF001
    byte_store._journal.close()  # noqa: SLF001


def test_worker_seal_denied_without_pin(tmp_path) -> None:
    """Without a pinned observer the worker seam stays closed (fail closed)."""
    _, profile, byte_store, _, _, store = _harness(tmp_path)
    store.declare(
        principal=_operator(),
        declaration=MaskChildDeclarationV1(
            declaration_id="decl-1",
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            child_kind="MASK_CHILD",
            mask_child_id="mask-child-1",
            mask_artifact_id="mask-artifact-1",
            parent_subject=_subject("parent"),
            target_baseline_subject=_subject("baseline"),
            target_baseline_dsm_artifact_id="dsm-baseline",
            declared_sha256=_digest("mask-bytes-x"),
            declared_size_bytes=64,
        ).sealed(),
        now=NOW,
    )
    with pytest.raises(PermissionError):
        store.seal_observed(
            principal=_designated_worker(),
            organization_id="org-a",
            mask_child_id="mask-child-1",
            report=_narrow_report(profile),
            inspection_profile=profile,
            now=NOW,
        )
    store._journal.close()  # noqa: SLF001
    byte_store._journal.close()  # noqa: SLF001
