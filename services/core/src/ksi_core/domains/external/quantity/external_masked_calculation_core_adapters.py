"""Genuine Core adapters for masked execution (P2, additive).

``CoreMaskedAdmissionEvidence`` bridges the REAL assessment/inspection state:

- source identity and evidence/WorkArea currentness via the real AP store
  (``prepare_execution_witness`` / ``execution_witness_is_current`` over the
  exact sealed source V2 identity digest) — a completed V2 numeric report is
  never required, only a current admitted assessment;
- mask-manifest currentness via the real ingress store (exact child, scope,
  baseline-anchor grid) plus the scoped protected-byte proof re-verified on
  every witness build;
- the exact pinned masked calculation profile (digest equality, no caller
  profile accepted);
- the real purpose-separated extension activation (``MASKED_ANALYSIS_V3``)
  bound to the independent masked profile digest, pinned runtime, pinned
  envelope, and designated worker, re-verified at every use;
- organization/site/work-area scope on every path.

AI egress: ordinary human read/write require no AI consent (the preserved
distinction); this adapter grants no egress itself.  MCP purpose gating, if
any, is enforced by the API guard outside, which may pass an explicit
purpose — the evidence port carries no caller purpose by design, so a
purpose can never be smuggled into admission through it.

``CoreMaskedAdmissionEvidence.bind_identity`` constructs the V3 identity
from the current AP source plus the current Core mask manifest (never from
caller-claimed bytes) and durably binds it in the calculation journal for
parent routes.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_masked_execution import (
    MaskedAdmissionDispositionV3,
    MaskedAdmissionV3,
    MaskedExecutionRuntimeV3,
    masked_execution_runtime_digest,
)
from ksi_event_contracts.external_masked_volume import (
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
    MaskedRelativeVolumeProfileV3,
)
from ksi_event_contracts.external_quantitative_extension_activation import (
    MASKED_ANALYSIS_PURPOSE,
    QuantitativeExtensionActivationV1,
)

from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
)
from ksi_core.domains.external.ingress.external_mask_input_store import (
    ExternalMaskInputStore,
)
from ksi_core.domains.external.quantity.external_masked_calculation_store import (
    ExternalMaskedCalculationStore,
    MaskedAdmissionEvidencePort,
    MaskedAdmissionWitnessV3,
)
from ksi_core.domains.external.quantity.external_quantitative_extension_activation import (
    load_quantitative_extension_activation,
)
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AdmissionDispositionV2,
    ExternalRelativeVolumeAnalysisStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Principal, PrincipalKind


def _digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _require_utc(now: datetime, description: str) -> None:
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise ValueError(f"{description} requires a UTC-aware time")


def _verified_activation_digest(activation: QuantitativeExtensionActivationV1) -> str:
    """Bind the actual verified activation record: id, key, issuance, window, signature.

    The digest covers the full canonical wire record including the detached
    signature, so a rotated key, reissued window, or different activation id
    can never match a stale admission digest.
    """
    return _digest(activation.model_dump(by_alias=True, mode="json"))


class CoreMaskedAdmissionEvidence(MaskedAdmissionEvidencePort):
    """Real masked-evidence witness over AP, ingress, bytes, profile, activation."""

    label = "core-masked-admission-evidence"

    def __init__(
        self,
        *,
        assessments: ExternalRelativeVolumeAnalysisStore,
        ingress: ExternalMaskInputStore,
        byte_store: ExternalMaskInputByteStore,
        masked_profile: MaskedRelativeVolumeProfileV3,
        pinned_execution_runtime: MaskedExecutionRuntimeV3,
        pinned_inspection_profile_digest: str,
        resource_envelope: ResourceEnvelopeV1,
        activation_path: Path,
        verification_keys_path: Path,
        organization_id: str,
        designated_worker: Principal,
        identity_resolver: Callable[[str, str], MaskedCalculationIdentityV3 | None] | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if not isinstance(assessments, ExternalRelativeVolumeAnalysisStore):
            raise ValueError("masked evidence requires the real AP assessment store")
        if not isinstance(ingress, ExternalMaskInputStore):
            raise ValueError("masked evidence requires the real mask ingress store")
        if not isinstance(byte_store, ExternalMaskInputByteStore):
            raise ValueError("masked evidence requires the real mask byte store")
        sealed_profile = MaskedRelativeVolumeProfileV3.model_validate(
            masked_profile.model_dump(by_alias=True)
        )
        if (
            sealed_profile.masked_profile_digest is None
            or sealed_profile.masked_profile_digest != sealed_profile.canonical_digest()
        ):
            raise ValueError("masked evidence requires a sealed pinned masked profile")
        if (
            resource_envelope.resource_envelope_digest is None
            or resource_envelope.resource_envelope_digest != resource_envelope.canonical_digest()
        ):
            raise ValueError("masked evidence requires a sealed resource envelope")
        if (
            designated_worker.kind is not PrincipalKind.ANALYSIS_WORKER
            or designated_worker.organization_id != organization_id
        ):
            raise ValueError("masked evidence requires the designated organization worker")
        sealed_runtime = MaskedExecutionRuntimeV3.model_validate(
            pinned_execution_runtime.model_dump(by_alias=True)
        )
        if (
            sealed_runtime.runtime_digest is None
            or sealed_runtime.runtime_digest != sealed_runtime.canonical_digest()
        ):
            raise ValueError("masked evidence requires a sealed pinned execution runtime")
        if _DIGEST_RE.fullmatch(pinned_inspection_profile_digest) is None:
            raise ValueError("masked evidence requires a valid pinned inspection profile digest")
        shared = coordinator or assessments.coordinator
        for name, participant in (
            ("assessments", assessments),
            ("ingress", ingress),
            ("byte store", byte_store),
        ):
            if participant.coordinator is not shared:
                raise ValueError(f"masked evidence {name} must share one coordinator")
        self._assessments = assessments
        self._ingress = ingress
        self._byte_store = byte_store
        self._masked_profile = sealed_profile.model_copy(deep=True)
        self._execution_runtime = sealed_runtime.model_copy(deep=True)
        self._pinned_inspection_profile_digest = pinned_inspection_profile_digest
        self._envelope = resource_envelope.model_copy(deep=True)
        self._activation_path = activation_path
        self._verification_keys_path = verification_keys_path
        self._organization_id = organization_id
        self._designated_worker = designated_worker
        self._resolver = identity_resolver
        self._coordinator = shared

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @property
    def masked_profile_digest(self) -> str:
        digest = self._masked_profile.masked_profile_digest
        assert digest is not None
        return digest

    @property
    def designated_worker(self) -> Principal:
        """The configured designated execution worker (frozen identity)."""
        return self._designated_worker

    def set_identity_resolver(
        self,
        resolver: Callable[[str, str], MaskedCalculationIdentityV3 | None],
    ) -> None:
        """Late-bind the Core-bound identity registry (usually the calc store)."""
        self._resolver = resolver

    def _resolve_identity(
        self, masked_digest: str, organization_id: str
    ) -> MaskedCalculationIdentityV3 | None:
        if self._resolver is None:
            return None
        try:
            return self._resolver(masked_digest, organization_id)
        except Exception:
            return None

    def _execution_runtime_digest(self) -> str:
        # Closed lane runtime: exact new 5-field execution worker plus the
        # masked profile, envelope, and narrow inspection profile digests.
        # Never a V2 runtime.
        return masked_execution_runtime_digest(
            self._execution_runtime,
            self.masked_profile_digest,
            self._envelope.canonical_digest(),
            self._pinned_inspection_profile_digest,
        )

    def _load_verified_activation(
        self, *, now: datetime
    ) -> QuantitativeExtensionActivationV1 | None:
        """Load the actually verified signed activation; None on any failure.

        Rotation, revocation, expiry, or key mismatch fails closed here, so an
        old admission digest can never stay authorized without the exact
        current authority.
        """
        try:
            return load_quantitative_extension_activation(
                self._activation_path,
                self._verification_keys_path,
                organization_id=self._organization_id,
                purpose=MASKED_ANALYSIS_PURPOSE,
                policy_digest=self.masked_profile_digest,
                runtime_digest=self._execution_runtime_digest(),
                resource_envelope_digest=self._envelope.canonical_digest(),
                worker_principal=self._designated_worker,
                now=now,
            )
        except Exception:
            return None

    @staticmethod
    def _masked_disposition_for_source(
        disposition: AdmissionDispositionV2,
    ) -> MaskedAdmissionDispositionV3 | None:
        # A mask calculation never upgrades accuracy or evidence status: a
        # provisional source stays provisional with its limitations.  Only a
        # currently evaluated source may yield an evaluated masked admission.
        if disposition is AdmissionDispositionV2.ADMIT_EVALUATED:
            return MaskedAdmissionDispositionV3.ADMIT_EVALUATED
        if disposition is AdmissionDispositionV2.ADMIT_PROVISIONAL:
            return MaskedAdmissionDispositionV3.ADMIT_PROVISIONAL
        return None

    def _admission_for(
        self,
        *,
        identity: MaskedCalculationIdentityV3,
        activation: QuantitativeExtensionActivationV1,
        source_disposition: AdmissionDispositionV2,
        source_reason_codes: tuple[str, ...],
        now: datetime,
    ) -> MaskedAdmissionV3:
        source = identity.source_calculation_identity
        disposition = self._masked_disposition_for_source(source_disposition)
        assert disposition is not None
        return MaskedAdmissionV3(
            admission_id="masked-admission-" + identity.canonical_digest()[7:23],
            organization_id=identity.organization_id,
            site_id=identity.site_id,
            work_area_id=identity.work_area_id,
            masked_calculation_identity_digest=identity.canonical_digest(),
            source_calculation_identity_digest=identity.source_calculation_identity_digest,
            mask_binding_digest=identity.mask_binding_digest,
            masked_profile_digest=identity.masked_profile_digest,
            area_definition_digest=source.work_area_definition_digest,
            policy_digest=self.masked_profile_digest,
            runtime_digest=self._execution_runtime_digest(),
            resource_envelope_digest=self._envelope.canonical_digest(),
            activation_digest=_verified_activation_digest(activation),
            scope_digest=_digest(
                {
                    "organizationId": identity.organization_id,
                    "siteId": identity.site_id,
                    "workAreaId": identity.work_area_id,
                }
            ),
            ai_egress_digest=_digest(
                {
                    "aiEgress": "NOT_GRANTED_AT_ADMISSION",
                    "organizationId": identity.organization_id,
                    "siteId": identity.site_id,
                    "workAreaId": identity.work_area_id,
                }
            ),
            disposition=disposition,
            reason_codes=("MASK_ADMITTED", *source_reason_codes[:63]),
            assessed_at=now,
        ).sealed()

    def _fresh_witness(
        self,
        *,
        masked_digest: str,
        organization_id: str,
        now: datetime,
        expected_admission: MaskedAdmissionV3 | None,
    ) -> MaskedAdmissionWitnessV3 | None:
        _require_utc(now, "masked evidence currentness")
        if organization_id != self._organization_id:
            return None
        identity = self._resolve_identity(masked_digest, organization_id)
        if identity is None:
            return None
        if identity.masked_calculation_identity_digest != masked_digest:
            return None
        if (
            identity.masked_profile_digest != self.masked_profile_digest
            or identity.organization_id != organization_id
        ):
            return None
        verified = self._load_verified_activation(now=now)
        if verified is None:
            return None
        source_digest = identity.source_calculation_identity_digest
        with self._coordinator.guarded_read():
            ap_witness = self._assessments.prepare_execution_witness(
                calculation_identity_digest=source_digest,
                organization_id=organization_id,
                now=now,
            )
            current = (
                self._assessments.execution_witness_is_current(witness=ap_witness, now=now)
                if ap_witness is not None
                else None
            )
            if current is None:
                return None
            if (
                current.admission.calculation_identity is None
                or current.admission.calculation_identity.canonical_digest() != source_digest
            ):
                return None
            source_disposition = current.admission.disposition
            if self._masked_disposition_for_source(source_disposition) is None:
                return None
            source_reasons = tuple(current.admission.reason_codes)
            manifest = self._ingress.resolve_manifest_by_child(
                organization_id=organization_id,
                mask_child_id=self._child_for_identity(identity),
            )
            if manifest is None:
                return None
            binding = identity.mask_binding
            if (
                manifest.observed_sha256 != binding.observed_sha256
                or manifest.observed_size_bytes != binding.observed_size_bytes
                or manifest.rows != identity.grid_rows
                or manifest.columns != identity.grid_columns
                or binding.observed_inspection_report_digest
                != manifest.observed_inspection_report_digest
            ):
                return None
            source = identity.source_calculation_identity
            anchor = self._ingress.resolve_baseline_anchor(
                organization_id=organization_id,
                site_id=identity.site_id,
                work_area_id=identity.work_area_id,
                baseline_subject=source.baseline_subject,
                dsm_artifact_id=source.baseline_dsm_artifact_id,
            )
            if (
                anchor is None
                or anchor.baseline_subject_digest != manifest.target_baseline_subject_digest
                or anchor.dsm_artifact_id != manifest.target_baseline_dsm_artifact_id
                or anchor.observed_sha256 != source.baseline_dsm_observed_sha256
                or anchor.observed_size_bytes != source.baseline_dsm_observed_size_bytes
                or anchor.rows != manifest.rows
                or anchor.columns != manifest.columns
                or tuple(anchor.transform) != tuple(manifest.transform)
                or anchor.transform_digest != manifest.transform_digest
                or anchor.crs_identifier != manifest.observed_crs_identifier
                or anchor.crs_digest != manifest.observed_crs_digest
            ):
                return None
            try:
                proof_sha, proof_size = self._byte_store.fetch_proof(
                    organization_id=manifest.organization_id,
                    site_id=manifest.site_id,
                    subject_digest=manifest.parent_subject_digest,
                    mask_child_id=manifest.mask_child_id,
                    mask_artifact_id=manifest.mask_artifact_id,
                )
            except ValueError:
                return None
            if proof_sha != binding.observed_sha256 or proof_size != binding.observed_size_bytes:
                return None
        if expected_admission is not None:
            if (
                expected_admission.masked_calculation_identity_digest != masked_digest
                or expected_admission.masked_profile_digest != identity.masked_profile_digest
                or expected_admission.mask_binding_digest != identity.mask_binding_digest
            ):
                return None
            if expected_admission.activation_digest != _verified_activation_digest(verified):
                return None
            if expected_admission.disposition != self._masked_disposition_for_source(
                source_disposition
            ):
                return None
            admission = expected_admission
        else:
            admission = self._admission_for(
                identity=identity,
                activation=verified,
                source_disposition=source_disposition,
                source_reason_codes=source_reasons,
                now=now,
            )
        return MaskedAdmissionWitnessV3(
            admission=admission,
            source_identity=identity,
            mask_manifest=manifest,
        )

    def _child_for_identity(self, identity: MaskedCalculationIdentityV3) -> str:
        # Resolution scans Core-bound ingress state (never caller claims);
        # ambiguity fails closed at the caller below.
        child_id = self._ingress.find_child_by_artifact(
            organization_id=identity.organization_id,
            mask_artifact_id=identity.mask_binding.mask_artifact_id,
            observed_sha256=identity.mask_binding.observed_sha256,
        )
        return child_id or ""

    def prepare_witness(
        self,
        *,
        masked_calculation_identity_digest: str,
        organization_id: str,
        now: datetime,
        expected_admission: MaskedAdmissionV3 | None = None,
    ) -> MaskedAdmissionWitnessV3 | None:
        return self._fresh_witness(
            masked_digest=masked_calculation_identity_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )

    def witness_is_current(
        self, *, witness: MaskedAdmissionWitnessV3 | None, now: datetime
    ) -> MaskedAdmissionWitnessV3 | None:
        if witness is None:
            return None
        _require_utc(now, "masked evidence currentness")
        witness_digest = witness.source_identity.masked_calculation_identity_digest
        if witness_digest is None:
            return None
        fresh = self._fresh_witness(
            masked_digest=witness_digest,
            organization_id=witness.source_identity.organization_id,
            now=now,
            expected_admission=witness.admission,
        )
        if fresh is None:
            return None
        if fresh.admission != witness.admission:
            return None
        if fresh.mask_manifest.canonical_digest() != witness.mask_manifest.canonical_digest():
            return None
        return fresh

    def bind_identity(
        self,
        *,
        calculations: ExternalMaskedCalculationStore,
        principal: Principal,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        masked_calculation_id: str,
        source_calculation_identity_digest: str,
        now: datetime,
    ) -> MaskedCalculationIdentityV3:
        """Construct and durably bind one V3 identity from current Core state.

        Intended for the parent create-route: resolves the current AP source
        identity plus the current Core mask manifest (never caller bytes),
        builds the exact-profile binding, and journals it in the calculation
        store.  Returns the sealed bound identity.
        """
        _require_utc(now, "masked identity binding")
        with self._coordinator.guarded_read():
            ap_witness = self._assessments.prepare_execution_witness(
                calculation_identity_digest=source_calculation_identity_digest,
                organization_id=organization_id,
                now=now,
            )
            current = (
                self._assessments.execution_witness_is_current(witness=ap_witness, now=now)
                if ap_witness is not None
                else None
            )
            if current is None or current.admission.calculation_identity is None:
                raise ValueError("masked source has no current admitted assessment")
            source = current.admission.calculation_identity
            manifest = self._ingress.resolve_manifest_by_child(
                organization_id=organization_id,
                mask_child_id=mask_child_id,
            )
            if manifest is None:
                raise ValueError("mask child has no current sealed manifest")
            if (manifest.organization_id, manifest.site_id, manifest.work_area_id) != (
                organization_id,
                site_id,
                work_area_id,
            ) or manifest.mask_child_id != mask_child_id:
                raise ValueError("mask manifest is outside the requested scope")
            anchor = self._ingress.resolve_baseline_anchor(
                organization_id=organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                baseline_subject=source.baseline_subject,
                dsm_artifact_id=source.baseline_dsm_artifact_id,
            )
            if (
                anchor is None
                or anchor.baseline_subject_digest != manifest.target_baseline_subject_digest
                or anchor.dsm_artifact_id != manifest.target_baseline_dsm_artifact_id
                or anchor.observed_sha256 != source.baseline_dsm_observed_sha256
                or anchor.observed_size_bytes != source.baseline_dsm_observed_size_bytes
                or anchor.rows != manifest.rows
                or anchor.columns != manifest.columns
            ):
                raise ValueError("mask manifest does not bind the anchored baseline")
        if self._masked_disposition_for_source(current.admission.disposition) is None:
            raise ValueError("masked source disposition cannot execute")
        if self._load_verified_activation(now=now) is None:
            raise ValueError("masked binding requires a verified activation")
        binding = ExclusionMaskBindingV1(
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            subject=manifest.subject,
            mask_artifact_id=manifest.mask_artifact_id,
            observed_sha256=manifest.observed_sha256,
            observed_size_bytes=manifest.observed_size_bytes,
            observed_inspection_report_digest=manifest.observed_inspection_report_digest,
            rows=manifest.rows,
            columns=manifest.columns,
            transform=manifest.transform,
            transform_digest=manifest.transform_digest,
            observed_crs_identifier=manifest.observed_crs_identifier,
            observed_crs_digest=manifest.observed_crs_digest,
            dtype="UINT8",
            band_count=1,
            retain_value=0,
            exclude_value=1,
            nodata_representation="NONE",
            bounds=manifest.bounds,
        ).sealed()
        identity = MaskedCalculationIdentityV3(
            masked_calculation_id=masked_calculation_id,
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            source_calculation_identity=source,
            source_calculation_identity_digest=source.canonical_digest(),
            mask_binding=binding,
            mask_binding_digest=binding.canonical_digest(),
            profile=self._masked_profile,
            masked_profile_digest=self.masked_profile_digest,
            grid_rows=manifest.rows,
            grid_columns=manifest.columns,
            horizontal_crs_digest=manifest.observed_crs_digest,
        ).sealed()
        return calculations.bind_constructed_identity(
            principal=principal, identity=identity, now=now
        )


__all__ = [
    "CoreMaskedAdmissionEvidence",
    "masked_execution_runtime_digest",
]
