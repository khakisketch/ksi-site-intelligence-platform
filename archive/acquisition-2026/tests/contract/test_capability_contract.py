"""CAP-1 canonical capability mapping/gate contract (REQ-ACQ-103, INV-041)."""

from __future__ import annotations

import inspect
import json
from enum import StrEnum
from itertools import product

import pytest
from ksi_core.capability.registry import CapabilityRegistry, seed_prd_spikes
from ksi_dji_gateway.adapters.catalog import CANDIDATE_PATH_CAPABILITIES
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_domain.capability_contract import (
    RUNTIME_ROUTE_REGISTRY_V1,
    CanonicalCapabilityRequirement,
    CanonicalTransportCapability,
    CapabilityGateVersion,
    CapabilityIntegrationPath,
    CapabilityMappingInterpreter,
    CapabilityMappingVersion,
    DeclaredCapabilitySupport,
    GatewayCapabilityObservation,
    InvalidCapabilityIdentityError,
    LegacyCapabilityCompatibility,
    LegacyCapabilitySemantic,
    LegacyTransportCapabilityAlias,
    OperationalCapabilityActivation,
    ProductCapabilityApproval,
    RouteEvidenceQualification,
    RuntimeRouteRegistry,
    RuntimeRouteRequirement,
    RuntimeRouteSubjectKind,
    SourceCapabilityId,
    SourceRequirementMismatchError,
    UnsupportedCapabilityGateVersionError,
    UnsupportedCapabilityMappingVersionError,
    UnsupportedCapabilityRouteError,
    canonicalize_legacy_transport_capability,
    parse_legacy_core_capability_state,
    resolve_capability_gate,
    resolve_capability_mapping,
)

_C = CanonicalTransportCapability
_P = CapabilityIntegrationPath
_S = SourceCapabilityId
_R = RuntimeRouteSubjectKind

_EXPECTED: dict[tuple[_C, _P], tuple[_S, ...]] = {
    (_C.WAYLINE_DELIVERY, _P.PSDK_MANIFOLD): (
        _S.SPIKE_DJI_04,
        _S.SPIKE_DJI_06,
        _S.SPIKE_DJI_07,
    ),
    (_C.WAYLINE_DELIVERY, _P.DJI_DOCK): (_S.SPIKE_DJI_04, _S.SPIKE_DJI_08),
    (_C.EDGE_DOWNLINK, _P.MANIFOLD_DIRECT): (_S.SPIKE_DJI_07,),
    (_C.EDGE_DOWNLINK, _P.MSDK_FIELD): (_S.SPIKE_DJI_06, _S.SPIKE_DJI_07),
    (_C.EDGE_UPLINK, _P.DJI_CLOUD): (_S.SPIKE_DJI_06,),
    (_C.EDGE_UPLINK, _P.PSDK_MANIFOLD): (_S.SPIKE_DJI_07,),
    (_C.EDGE_UPLINK, _P.MANIFOLD_DIRECT): (_S.SPIKE_DJI_07,),
    (_C.MEDIA_PULL, _P.PSDK_MANIFOLD): (_S.SPIKE_DJI_02, _S.SPIKE_DJI_07),
    (_C.MEDIA_PULL, _P.MSDK_FIELD): (_S.SPIKE_DJI_02, _S.SPIKE_DJI_06),
    (_C.MEDIA_PULL, _P.DJI_DOCK): (_S.SPIKE_DJI_02, _S.SPIKE_DJI_08),
    (_C.MEDIA_UPLOAD, _P.MANIFOLD_DIRECT): (_S.SPIKE_DJI_07,),
    (_C.MEDIA_UPLOAD, _P.DJI_DOCK): (_S.SPIKE_DJI_08,),
}

_RUNTIME_EXPECTED: dict[tuple[_C, _P], _R] = {
    (_C.EDGE_UPLINK, _P.DJI_CLOUD): _R.GATEWAY_ROUTE_PORT,
    (_C.MEDIA_PULL, _P.DJI_DOCK): _R.DOCK_ROUTE_PORT,
    (_C.MEDIA_UPLOAD, _P.DJI_DOCK): _R.DOCK_ROUTE_PORT,
    (_C.WAYLINE_DELIVERY, _P.DJI_DOCK): _R.DOCK_ROUTE_PORT,
    (_C.EDGE_DOWNLINK, _P.MANIFOLD_DIRECT): _R.EDGE_ROUTE_PORT,
    (_C.EDGE_UPLINK, _P.MANIFOLD_DIRECT): _R.EDGE_ROUTE_PORT,
    (_C.MEDIA_UPLOAD, _P.MANIFOLD_DIRECT): _R.EDGE_ROUTE_PORT,
    (_C.EDGE_DOWNLINK, _P.MSDK_FIELD): _R.GATEWAY_EDGE_ROUTE_PORT,
    (_C.MEDIA_PULL, _P.MSDK_FIELD): _R.GATEWAY_EDGE_ROUTE_PORT,
    (_C.EDGE_UPLINK, _P.PSDK_MANIFOLD): _R.EDGE_ROUTE_PORT,
    (_C.MEDIA_PULL, _P.PSDK_MANIFOLD): _R.EDGE_ROUTE_PORT,
    (_C.WAYLINE_DELIVERY, _P.PSDK_MANIFOLD): _R.EDGE_ROUTE_PORT,
}

_UNMAPPED_RUNTIME_TUPLES = tuple(
    sorted(
        set(product(_C, _P)) - set(_RUNTIME_EXPECTED),
        key=lambda item: (item[1].value, item[0].value),
    )
)


def _mapping() -> CapabilityMappingInterpreter:
    return resolve_capability_mapping("ksi-dji-capability-map-v1")


def _runtime_routes() -> RuntimeRouteRegistry:
    return RUNTIME_ROUTE_REGISTRY_V1


def test_five_semantic_types_have_disjoint_domain_qualified_wire_values() -> None:
    semantic_types = (
        DeclaredCapabilitySupport,
        GatewayCapabilityObservation,
        RouteEvidenceQualification,
        ProductCapabilityApproval,
        OperationalCapabilityActivation,
    )
    value_sets = [{item.value for item in semantic} for semantic in semantic_types]
    assert all("VERIFIED" not in values for values in value_sets)
    assert len(set().union(*value_sets)) == sum(len(values) for values in value_sets)
    assert all(":" in value for values in value_sets for value in values)


def test_cross_domain_members_with_same_status_word_are_not_equal() -> None:
    assert RouteEvidenceQualification.REVOKED != ProductCapabilityApproval.REVOKED
    assert ProductCapabilityApproval.REVOKED != OperationalCapabilityActivation.REVOKED
    assert RouteEvidenceQualification.BLOCKED != ProductCapabilityApproval.BLOCKED
    assert GatewayCapabilityObservation.UNKNOWN != DeclaredCapabilitySupport.UNKNOWN


def test_cross_domain_members_do_not_collapse_in_set_or_dict_keys() -> None:
    members: tuple[StrEnum, ...] = (
        RouteEvidenceQualification.REVOKED,
        ProductCapabilityApproval.REVOKED,
        OperationalCapabilityActivation.REVOKED,
        RouteEvidenceQualification.BLOCKED,
        ProductCapabilityApproval.BLOCKED,
        GatewayCapabilityObservation.UNKNOWN,
        DeclaredCapabilitySupport.UNKNOWN,
    )
    assert len(set(members)) == len(members)
    keyed = {member: member.__class__.__name__ for member in members}
    assert len(keyed) == len(members)
    assert keyed[RouteEvidenceQualification.REVOKED] == "RouteEvidenceQualification"
    assert keyed[ProductCapabilityApproval.REVOKED] == "ProductCapabilityApproval"
    assert keyed[OperationalCapabilityActivation.REVOKED] == (
        "OperationalCapabilityActivation"
    )


@pytest.mark.parametrize(
    ("semantic_type", "member"),
    [
        (DeclaredCapabilitySupport, DeclaredCapabilitySupport.UNKNOWN),
        (GatewayCapabilityObservation, GatewayCapabilityObservation.UNKNOWN),
        (RouteEvidenceQualification, RouteEvidenceQualification.REVOKED),
        (ProductCapabilityApproval, ProductCapabilityApproval.REVOKED),
        (OperationalCapabilityActivation, OperationalCapabilityActivation.REVOKED),
    ],
)
def test_semantic_state_canonical_json_round_trip_preserves_domain(
    semantic_type: type[StrEnum], member: StrEnum
) -> None:
    encoded = canonical_json_bytes({"semanticState": member.value})
    decoded = json.loads(encoded)["semanticState"]
    assert semantic_type(decoded) is member


def test_revoked_wire_value_cannot_deserialize_in_another_semantic_domain() -> None:
    with pytest.raises(ValueError):
        ProductCapabilityApproval(RouteEvidenceQualification.REVOKED.value)
    with pytest.raises(ValueError):
        OperationalCapabilityActivation(ProductCapabilityApproval.REVOKED.value)


def test_canonical_transport_ids_are_exact_and_closed() -> None:
    assert {item.value for item in _C} == {
        "WAYLINE_DELIVERY",
        "EDGE_DOWNLINK",
        "EDGE_UPLINK",
        "MEDIA_PULL",
        "MEDIA_UPLOAD",
    }
    with pytest.raises(ValueError):
        _C("WAYLINE_PUSH")


def test_source_capability_ids_are_exactly_the_current_core_spike_seed() -> None:
    registry = CapabilityRegistry()
    seed_prd_spikes(registry)
    assert {item.value for item in _S} == {record.capability_id for record in registry.list_all()}


def test_gateway_legacy_aliases_require_explicit_canonicalization() -> None:
    assert {
        alias: canonicalize_legacy_transport_capability(alias)
        for alias in LegacyTransportCapabilityAlias
    } == {
        LegacyTransportCapabilityAlias.WAYLINE_PUSH: _C.WAYLINE_DELIVERY,
        LegacyTransportCapabilityAlias.TASK_STATUS: _C.EDGE_UPLINK,
        LegacyTransportCapabilityAlias.CAMERA_MEDIA_PULL: _C.MEDIA_PULL,
    }
    with pytest.raises(InvalidCapabilityIdentityError):
        canonicalize_legacy_transport_capability("UNKNOWN_ALIAS")


def test_executable_gateway_catalog_is_exactly_the_approved_twelve_pairs() -> None:
    catalog = {
        (_C(capability.value), _P(path.value))
        for path, capabilities in CANDIDATE_PATH_CAPABILITIES.items()
        for capability in capabilities
    }
    assert len(catalog) == 12
    assert catalog == set(_EXPECTED)


def test_mapping_covers_exactly_twelve_without_extra_or_missing_pair() -> None:
    actual = {
        (item.canonical_capability, item.integration_path): item.required_sources
        for item in _mapping().all_requirements()
    }
    assert len(actual) == 12
    assert actual == _EXPECTED


def test_runtime_route_subject_kind_is_exact_and_closed() -> None:
    assert {item.value for item in _R} == {
        "GATEWAY_ROUTE_PORT",
        "DOCK_ROUTE_PORT",
        "EDGE_ROUTE_PORT",
        "GATEWAY_EDGE_ROUTE_PORT",
    }
    with pytest.raises(ValueError):
        _R("GATEWAY_PORT")


def test_runtime_route_registry_has_exact_v1_twelve_rows_and_subject_assignments() -> None:
    requirements = _runtime_routes().all_requirements()
    actual = {
        (item.canonical_capability, item.integration_path): item.subject_kind
        for item in requirements
    }
    assert len(requirements) == 12
    assert actual == _RUNTIME_EXPECTED
    assert all(item.requires_current_observation for item in requirements)
    assert [
        (item.integration_path.value, item.canonical_capability.value) for item in requirements
    ] == sorted(
        (path.value, capability.value) for capability, path in _RUNTIME_EXPECTED
    )


def test_runtime_route_requirement_cannot_weaken_current_observation_requirement() -> None:
    with pytest.raises(UnsupportedCapabilityRouteError):
        RuntimeRouteRequirement(
            canonical_capability=_C.EDGE_UPLINK,
            integration_path=_P.DJI_CLOUD,
            subject_kind=_R.GATEWAY_ROUTE_PORT,
            requires_current_observation=False,
        )


@pytest.mark.parametrize(
    ("capability", "path"),
    _UNMAPPED_RUNTIME_TUPLES,
    ids=lambda item: item.value,
)
def test_runtime_route_registry_rejects_each_of_the_thirteen_unmapped_tuples(
    capability: _C, path: _P
) -> None:
    assert len(_UNMAPPED_RUNTIME_TUPLES) == 13
    with pytest.raises(UnsupportedCapabilityRouteError):
        _runtime_routes().requirement_for(capability, path)


def test_edge_uplink_runtime_requirements_keep_direct_and_psdk_paths_distinct() -> None:
    direct = _runtime_routes().requirement_for(_C.EDGE_UPLINK, _P.MANIFOLD_DIRECT)
    psdk = _runtime_routes().requirement_for(_C.EDGE_UPLINK, _P.PSDK_MANIFOLD)
    assert direct.subject_kind is psdk.subject_kind is _R.EDGE_ROUTE_PORT
    assert direct.integration_path is _P.MANIFOLD_DIRECT
    assert psdk.integration_path is _P.PSDK_MANIFOLD
    assert direct != psdk


@pytest.mark.parametrize(
    "source",
    [_S.SPIKE_DJI_01, _S.SPIKE_DJI_03, _S.SPIKE_DJI_05, _S.SPIKE_DJI_09],
)
def test_intentionally_unmapped_source_never_gains_transport_mapping(source: _S) -> None:
    mapping = _mapping()
    assert source in mapping.intentionally_unmapped_sources
    assert not mapping.is_source_mapped(source)
    for path in _P:
        with pytest.raises(UnsupportedCapabilityRouteError):
            mapping.requirements_for_source_path(source, path)


def test_intentionally_unmapped_source_list_is_exact() -> None:
    assert _mapping().intentionally_unmapped_sources == (
        _S.SPIKE_DJI_01,
        _S.SPIKE_DJI_03,
        _S.SPIKE_DJI_05,
        _S.SPIKE_DJI_09,
    )


def test_direct_downlink_07_does_not_satisfy_msdk_downlink() -> None:
    mapping = _mapping()
    direct = mapping.validate_required_sources(
        _C.EDGE_DOWNLINK, _P.MANIFOLD_DIRECT, (_S.SPIKE_DJI_07,)
    )
    assert direct.required_sources == (_S.SPIKE_DJI_07,)
    with pytest.raises(SourceRequirementMismatchError):
        mapping.validate_required_sources(
            _C.EDGE_DOWNLINK, _P.MSDK_FIELD, (_S.SPIKE_DJI_07,)
        )


def test_msdk_downlink_requires_06_and_07() -> None:
    result = _mapping().validate_required_sources(
        _C.EDGE_DOWNLINK,
        _P.MSDK_FIELD,
        (_S.SPIKE_DJI_07, _S.SPIKE_DJI_06),
    )
    assert result.required_sources == (_S.SPIKE_DJI_06, _S.SPIKE_DJI_07)


def test_psdk_media_pull_does_not_satisfy_dock_media_pull() -> None:
    mapping = _mapping()
    mapping.validate_required_sources(
        _C.MEDIA_PULL, _P.PSDK_MANIFOLD, (_S.SPIKE_DJI_02, _S.SPIKE_DJI_07)
    )
    with pytest.raises(SourceRequirementMismatchError):
        mapping.validate_required_sources(
            _C.MEDIA_PULL, _P.DJI_DOCK, (_S.SPIKE_DJI_02, _S.SPIKE_DJI_07)
        )


def test_dock_media_pull_requires_02_and_08() -> None:
    result = _mapping().requirement_for(_C.MEDIA_PULL, _P.DJI_DOCK)
    assert result.required_sources == (_S.SPIKE_DJI_02, _S.SPIKE_DJI_08)


def test_psdk_wayline_requires_exact_04_06_07() -> None:
    result = _mapping().requirement_for(_C.WAYLINE_DELIVERY, _P.PSDK_MANIFOLD)
    assert result.required_sources == (
        _S.SPIKE_DJI_04,
        _S.SPIKE_DJI_06,
        _S.SPIKE_DJI_07,
    )
    with pytest.raises(SourceRequirementMismatchError):
        _mapping().validate_required_sources(
            _C.WAYLINE_DELIVERY,
            _P.PSDK_MANIFOLD,
            (_S.SPIKE_DJI_04, _S.SPIKE_DJI_06),
        )


def test_dock_wayline_requires_exact_04_08() -> None:
    result = _mapping().requirement_for(_C.WAYLINE_DELIVERY, _P.DJI_DOCK)
    assert result.required_sources == (_S.SPIKE_DJI_04, _S.SPIKE_DJI_08)


def test_source_path_lookup_retains_every_matching_canonical_requirement() -> None:
    matches = _mapping().requirements_for_source_path(_S.SPIKE_DJI_07, _P.PSDK_MANIFOLD)
    assert {(item.canonical_capability, item.integration_path) for item in matches} == {
        (_C.WAYLINE_DELIVERY, _P.PSDK_MANIFOLD),
        (_C.EDGE_UPLINK, _P.PSDK_MANIFOLD),
        (_C.MEDIA_PULL, _P.PSDK_MANIFOLD),
    }
    assert all(_S.SPIKE_DJI_07 in item.required_sources for item in matches)


@pytest.mark.parametrize(
    ("capability", "path"),
    [
        (_C.WAYLINE_DELIVERY, _P.DJI_CLOUD),
        (_C.EDGE_DOWNLINK, _P.PSDK_MANIFOLD),
        (_C.MEDIA_UPLOAD, _P.MSDK_FIELD),
    ],
)
def test_nonexistent_or_unapproved_capability_path_is_rejected(
    capability: _C, path: _P
) -> None:
    with pytest.raises(UnsupportedCapabilityRouteError):
        _mapping().requirement_for(capability, path)


@pytest.mark.parametrize(
    ("method", "value"),
    [
        ("capability", "NOT_A_CAPABILITY"),
        ("path", "NOT_A_PATH"),
        ("source", "SPIKE-DJI-99"),
    ],
)
def test_unknown_identity_fails_closed(method: str, value: str) -> None:
    mapping = _mapping()
    with pytest.raises(InvalidCapabilityIdentityError):
        if method == "capability":
            mapping.requirement_for(value, _P.DJI_DOCK)
        elif method == "path":
            mapping.requirement_for(_C.MEDIA_PULL, value)
        else:
            mapping.requirements_for_source_path(value, _P.DJI_DOCK)


def test_mapping_v1_resolves_deterministically_for_enum_and_string() -> None:
    assert resolve_capability_mapping(CapabilityMappingVersion.V1) is _mapping()
    assert _mapping().version is CapabilityMappingVersion.V1


@pytest.mark.parametrize("version", [None, "", "latest", "ksi-dji-capability-map-v2"])
def test_missing_or_unknown_mapping_version_fails_closed(version: str | None) -> None:
    with pytest.raises(UnsupportedCapabilityMappingVersionError):
        resolve_capability_mapping(version)


def test_mapping_resolver_has_no_implicit_latest_default() -> None:
    parameter = inspect.signature(resolve_capability_mapping).parameters["version"]
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        resolve_capability_mapping()  # type: ignore[call-arg]


def test_gate_v1_resolves_as_identity_only() -> None:
    gate = resolve_capability_gate("ksi-capability-gate-v1")
    assert gate.version is CapabilityGateVersion.V1
    assert gate.canonical_payload() == {"gateVersion": "ksi-capability-gate-v1"}


@pytest.mark.parametrize("version", [None, "", "latest", "ksi-capability-gate-v2"])
def test_missing_or_unknown_gate_version_fails_closed(version: str | None) -> None:
    with pytest.raises(UnsupportedCapabilityGateVersionError):
        resolve_capability_gate(version)


def test_gate_resolver_has_no_implicit_latest_default() -> None:
    parameter = inspect.signature(resolve_capability_gate).parameters["version"]
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        resolve_capability_gate()  # type: ignore[call-arg]


def test_requirement_retains_capability_path_sources_and_mapping_version() -> None:
    result = _mapping().requirement_for(_C.MEDIA_PULL, _P.PSDK_MANIFOLD)
    assert result.canonical_capability is _C.MEDIA_PULL
    assert result.integration_path is _P.PSDK_MANIFOLD
    assert result.required_sources == (_S.SPIKE_DJI_02, _S.SPIKE_DJI_07)
    assert result.mapping_version is CapabilityMappingVersion.V1


def test_manual_requirement_cannot_invent_or_weaken_mapping() -> None:
    with pytest.raises(UnsupportedCapabilityRouteError):
        CanonicalCapabilityRequirement(
            canonical_capability=_C.MEDIA_PULL,
            integration_path=_P.DJI_DOCK,
            required_sources=(_S.SPIKE_DJI_02,),
            mapping_version=CapabilityMappingVersion.V1,
        )


def test_same_logical_requirement_has_identical_canonical_bytes_regardless_input_order() -> None:
    mapping = _mapping()
    direct = mapping.requirement_for(_C.WAYLINE_DELIVERY, _P.PSDK_MANIFOLD)
    reordered = mapping.validate_required_sources(
        _C.WAYLINE_DELIVERY,
        _P.PSDK_MANIFOLD,
        (_S.SPIKE_DJI_07, _S.SPIKE_DJI_04, _S.SPIKE_DJI_06),
    )
    assert direct == reordered
    assert direct.canonical_bytes() == reordered.canonical_bytes()


def test_duplicate_or_extra_source_is_rejected_instead_of_disappearing() -> None:
    with pytest.raises(SourceRequirementMismatchError):
        _mapping().validate_required_sources(
            _C.MEDIA_PULL,
            _P.DJI_DOCK,
            (_S.SPIKE_DJI_02, _S.SPIKE_DJI_08, _S.SPIKE_DJI_08),
        )
    with pytest.raises(SourceRequirementMismatchError):
        _mapping().validate_required_sources(
            _C.MEDIA_PULL,
            _P.DJI_DOCK,
            (_S.SPIKE_DJI_02, _S.SPIKE_DJI_07, _S.SPIKE_DJI_08),
        )


def test_path_and_mapping_version_are_digest_inputs() -> None:
    psdk = _mapping().requirement_for(_C.EDGE_UPLINK, _P.PSDK_MANIFOLD)
    direct = _mapping().requirement_for(_C.EDGE_UPLINK, _P.MANIFOLD_DIRECT)
    assert psdk.canonical_bytes() != direct.canonical_bytes()
    future_payload = psdk.canonical_payload() | {"mappingVersion": "ksi-dji-capability-map-v2"}
    assert psdk.canonical_bytes() != canonical_json_bytes(future_payload)


def test_mapping_and_gate_binding_has_stable_complete_digest_input() -> None:
    requirement = _mapping().requirement_for(_C.MEDIA_UPLOAD, _P.DJI_DOCK)
    binding = resolve_capability_gate(CapabilityGateVersion.V1).bind(requirement)
    assert binding.canonical_bytes() == (
        b'{"canonicalCapabilityId":"MEDIA_UPLOAD","gateVersion":"ksi-capability-gate-v1",'
        b'"integrationPath":"DJI_DOCK","mappingVersion":"ksi-dji-capability-map-v1",'
        b'"requiredSourceCapabilityIds":["SPIKE-DJI-08"]}'
    )


def test_legacy_verified_is_unattested_and_has_zero_authority() -> None:
    parsed = parse_legacy_core_capability_state("VERIFIED")
    assert parsed.semantic is LegacyCapabilitySemantic.LEGACY_UNATTESTED
    assert not parsed.has_evidence_authority
    assert not parsed.has_approval_authority
    assert not parsed.has_activation_authority
    assert parsed.semantic is not ProductCapabilityApproval.APPROVED


def test_legacy_verified_round_trip_cannot_strengthen_authority() -> None:
    first = parse_legacy_core_capability_state("VERIFIED")
    second = parse_legacy_core_capability_state(first.serialize_legacy())
    assert first == second
    assert second.semantic is LegacyCapabilitySemantic.LEGACY_UNATTESTED
    assert not second.has_approval_authority and not second.has_activation_authority


def test_legacy_compatibility_envelope_cannot_be_constructed_with_stronger_semantic() -> None:
    with pytest.raises(InvalidCapabilityIdentityError):
        LegacyCapabilityCompatibility(
            source_value="VERIFIED",
            semantic=LegacyCapabilitySemantic.APPROVAL_REQUIRED,
        )


def test_unknown_legacy_state_is_not_coerced() -> None:
    with pytest.raises(InvalidCapabilityIdentityError):
        parse_legacy_core_capability_state("APPROVED")


def test_cap1_module_exposes_no_durable_authority_record_or_journal() -> None:
    import ksi_domain.capability_contract as contract

    forbidden = {
        "CapabilityEvidenceRecordV1",
        "ProductCapabilityApprovalRecordV1",
        "OperationalCapabilityActivationRecordV1",
        "CapabilityAuthorityJournal",
    }
    assert forbidden.isdisjoint(vars(contract))
