"""C1: scoped customer OIDC may inspect and submit evidence; scope enforced.

Valid FIELD_OPERATOR with explicit Site/WorkArea grants reaches exactly the
reviewed inspection read and evidence declare/grant/seal/list routes. Cross-org,
same-org ungranted Site/WorkArea, and empty-area orders fail closed as 404;
revoked mappings are 401; worker/internal routes stay closed (403).
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key
from fastapi import Depends
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    HumanAuthMode,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    require_principal,
)
from ksi_core.domains.observations.epoch_identity import observation_epoch_id
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_core.external_artifact_inspections import ExternalArtifactInspectionStore
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_display_artifacts import ExternalDisplayArtifactStore
from ksi_core.external_evidence import ExternalEvidenceStore
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.external_validation_policy import ExternalValidationPolicyRegistry
from ksi_core.identity.auth import _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig
from ksi_core.sites import SiteStore
from ksi_event_contracts.external_reconstruction import ExternalReconstructionSubmissionV1
from ksi_event_contracts.site_frame import SiteFrame

_ISSUER = "https://customer-oidc.example.test"
_AUDIENCE = "ksi-core-customer"
_NOW = datetime(2026, 9, 8, tzinfo=UTC)
_OPAQUE_ADMIN = "c1-setup-admin"  # noqa: S105 -- deterministic test credential
_OPAQUE_ADMIN_B = "c1-setup-admin-b"  # noqa: S105 -- deterministic test credential
_SETUP_SUBMITTED_BY = {"org-a": "setup-admin", "org-b": "setup-admin-b"}
_SETUP_TOKENS = {"org-a": _OPAQUE_ADMIN, "org-b": _OPAQUE_ADMIN_B}

_EVIDENCE_BASE = (
    "/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}"
)
_EVIDENCE_ROUTES = {
    ("POST", "/v1/observation-work-orders" + _EVIDENCE_BASE + "/evidence"),
    ("GET", "/v1/observation-work-orders" + _EVIDENCE_BASE + "/evidence"),
    (
        "POST",
        "/v1/observation-work-orders" + _EVIDENCE_BASE + "/evidence/{evidence_ref}/upload-grant",
    ),
    (
        "POST",
        "/v1/observation-work-orders" + _EVIDENCE_BASE + "/evidence/{evidence_ref}/seal",
    ),
}
_INSPECTION_ROUTES = {
    ("GET", "/v1/observation-work-orders" + _EVIDENCE_BASE + "/inspection"),
    (
        "GET",
        "/v1/observation-work-orders"
        + _EVIDENCE_BASE
        + "/display-artifacts/{sanitized_display_ref}/download",
    ),
}

# Worker/internal routes must never admit the scoped customer principal.
_CLOSED_WORKER_ROUTES = {
    ("GET", "/v1/internal/external-validation/inspections"),
    ("POST", "/v1/internal/external-validation/inspections/{request_id}/lease"),
    ("GET", "/v1/internal/external-validation/inspections/{request_id}/input"),
    ("GET", "/v1/internal/external-validation/evidence-validations"),
}


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, ObjectStorageObservation] = {}

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: Any
    ) -> DigestBoundUploadCapability:
        del ttl
        return DigestBoundUploadCapability(
            upload_url=f"https://storage.invalid/put/{object_key}",
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": content_digest,
            },
        )

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self.objects.get(object_key, ObjectStorageObservation(object_key, exists=False))


def _jwk(key: RSAPrivateKey) -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    encode = lambda value: jwt.utils.base64url_encode(  # noqa: E731
        value.to_bytes((value.bit_length() + 7) // 8, "big")
    ).decode()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "customer-key-1",
        "n": encode(numbers.n),
        "e": encode(numbers.e),
    }


def _subject_rows(*, status: str = "ACTIVE") -> list[dict[str, Any]]:
    return [
        {
            "issuer": _ISSUER,
            "subject": "customer-field-op",
            "principalId": "customer-field-op",
            "organizationId": "org-a",
            "role": "FIELD_OPERATOR",
            "status": status,
            "allowedSiteIds": ["site-a"],
            "allowedWorkAreaIds": ["wa-a"],
        },
        {
            "issuer": _ISSUER,
            "subject": "foreign-op",
            "principalId": "foreign-op",
            "organizationId": "org-b",
            "role": "FIELD_OPERATOR",
            "status": "ACTIVE",
            "allowedSiteIds": ["site-b"],
            "allowedWorkAreaIds": ["wa-b"],
        },
    ]


def _install_oidc(app: Any, key: RSAPrivateKey, *, status: str = "ACTIVE") -> None:
    registry = OidcSubjectRegistry.from_document(
        {"version": "oidc-subject-registry.v1", "subjects": _subject_rows(status=status)},
        expected_issuer=_ISSUER,
    )
    app.state.human_auth_mode = HumanAuthMode.OIDC
    app.state.oidc_verifier = OidcJwtVerifier(
        OidcVerifierConfig(issuer=_ISSUER, audience=_AUDIENCE, jwks_url=f"{_ISSUER}/jwks.json"),
        fetch_jwks=lambda: {"keys": [_jwk(key)]},
        subject_registry=registry,
    )


def _token(key: RSAPrivateKey, subject: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": _ISSUER, "aud": _AUDIENCE, "sub": subject, "exp": now + 600, "nbf": now - 5},
        key,
        algorithm="RS256",
        headers={"kid": "customer-key-1"},
    )


class _Fixture:
    def __init__(self, tmp_path: Path, *, status: str = "ACTIVE") -> None:
        self.key = generate_private_key(public_exponent=65537, key_size=2048)
        sites = SiteStore(DurableJournal(tmp_path / f"sites-{status}.jsonl"))
        frame = SiteFrame(
            crs="EPSG:5186", vertical_datum="KNGeoid2018", unit="meter", transform_version="1.0.0"
        )
        for site_id, org in (("site-a", "org-a"), ("site-a2", "org-a"), ("site-b", "org-b")):
            assert sites.register(
                site_id, site_id, frame, organization_id=org, actor="test", now=_NOW
            ).record
        work_orders = ObservationWorkOrderStore(
            DurableJournal(tmp_path / f"orders-{status}.jsonl"),
            site_exists=lambda site_id, organization_id: (
                sites.get_scoped(site_id, organization_id) is not None
            ),
        )
        self.orders: dict[str, str] = {}
        for name, org, site, areas in (
            ("granted", "org-a", "site-a", ["wa-a"]),
            ("ungranted-site", "org-a", "site-a2", ["wa-a"]),
            ("ungranted-area", "org-a", "site-a", ["wa-other"]),
            ("foreign", "org-b", "site-b", ["wa-b"]),
        ):
            order = work_orders.create_work_order(
                organization_id=org,
                site_id=site,
                name=f"C1 {name}",
                work_area_ids=list(areas),
                schedule_id=None,
                actor="test",
                now=_NOW,
            )
            self.orders[name] = order.work_order_id
        self.storage = _Storage()
        recon = ExternalReconstructionStore(DurableJournal(tmp_path / f"recon-{status}.jsonl"))
        evidence = ExternalEvidenceStore(DurableJournal(tmp_path / f"evidence-{status}.jsonl"))
        coordinator = ExternalAuthorityCurrentnessCoordinator()
        policies = ExternalValidationPolicyRegistry(
            DurableJournal(tmp_path / f"policies-{status}.jsonl"),
            coordinator=coordinator,
        )
        display = ExternalDisplayArtifactStore(
            DurableJournal(tmp_path / f"display-{status}.jsonl"),
            policy_registry=policies,
            storage=cast(Any, self.storage),
            coordinator=coordinator,
        )
        inspections = ExternalArtifactInspectionStore(
            DurableJournal(tmp_path / f"inspections-{status}.jsonl"),
            policy_registry=policies,
            external_reconstruction=recon,
            storage=cast(Any, self.storage),
            display_store=display,
            coordinator=coordinator,
        )
        app = create_app(
            auth_registry=AuthRegistry(
                [
                    PrincipalTokenRecord(
                        token_sha256=hashlib.sha256(_OPAQUE_ADMIN.encode()).hexdigest(),
                        principal=Principal(
                            principal_id="setup-admin",
                            kind=PrincipalKind.OPERATOR,
                            role=Role.ADMIN,
                            device_id=None,
                            organization_id="org-a",
                        ),
                    ),
                    PrincipalTokenRecord(
                        token_sha256=hashlib.sha256(_OPAQUE_ADMIN_B.encode()).hexdigest(),
                        principal=Principal(
                            principal_id="setup-admin-b",
                            kind=PrincipalKind.OPERATOR,
                            role=Role.ADMIN,
                            device_id=None,
                            organization_id="org-b",
                        ),
                    ),
                ]
            ),
            site_store=sites,
            observation_work_order_store=work_orders,
            evidence_storage=cast(Any, self.storage),
            external_reconstruction_store=recon,
            external_evidence_store=evidence,
            external_display_artifact_store=display,
            external_artifact_inspection_store=inspections,
        )

        @app.get("/v1/sites/{site_id}/analyses/result/export")
        def unreviewed_export(
            site_id: str,
            principal: Principal = Depends(require_principal()),  # noqa: B008
        ) -> dict[str, str]:
            return {"siteId": site_id, "principalId": principal.principal_id}

        self.app = app
        self.client = TestClient(app)
        self.refs: dict[str, str] = {}
        for name, org in (
            ("granted", "org-a"),
            ("ungranted-site", "org-a"),
            ("ungranted-area", "org-a"),
            ("foreign", "org-b"),
        ):
            self.refs[name] = self._seal(name, org)
        _install_oidc(app, self.key, status=status)
        self.headers_a = {"Authorization": f"Bearer {_token(self.key, 'customer-field-op')}"}
        self.headers_b = {"Authorization": f"Bearer {_token(self.key, 'foreign-op')}"}

    def _seal(self, name: str, org: str) -> str:
        work_order_id = self.orders[name]
        order = cast(Any, self.app).state.observation_work_order_store.get(
            work_order_id, organization_id=org
        )
        artifacts = []
        for artifact_id, payload in (("ortho", b"ortho"), ("dsm", b"dsm")):
            artifacts.append(
                {
                    "artifactId": artifact_id,
                    "kind": artifact_id,
                    "fileName": f"{artifact_id}.tif",
                    "format": "GeoTIFF",
                    "contentType": "application/octet-stream",
                    "declaredSha256": hashlib.sha256(payload).hexdigest(),
                    "declaredSizeBytes": len(payload),
                    "declaredCrs": None,
                    "declaredVerticalReference": None,
                    "declaredGsdM": None,
                }
            )
        submission: dict[str, Any] = {
            "submissionId": f"c1-{name}",
            "revision": 1,
            "organizationId": org,
            "siteId": order.site_id,
            "observationEpochId": observation_epoch_id(order),
            "submittedAt": "2026-09-08T00:00:00Z",
            "submittedBy": _SETUP_SUBMITTED_BY[org],
            "executionResponsibility": "customer_operator",
            "executionLocus": "customer_workstation",
            "producerDeclaration": {
                "softwareName": "Customer Mapper",
                "softwareVersion": "1.0",
                "buildIdentifier": None,
                "producerRunIdentifier": None,
                "configurationDigest": None,
                "completedAt": None,
            },
            "inputDeclaration": {
                "rawMediaStoredByKsi": False,
                "originalRetentionLocus": "customer_workstation",
                "localInputManifestDigest": None,
                "imageCount": None,
                "captureStartedAt": None,
                "captureEndedAt": None,
            },
            "artifacts": artifacts,
        }
        submission["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(
            submission
        )
        setup = {"Authorization": f"Bearer {_SETUP_TOKENS[org]}"}
        root = f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions"
        registered = self.client.post(root, headers=setup, json=submission)
        assert registered.status_code == 201, registered.text
        ref = registered.json()["submissionRef"]
        grants = self.client.post(f"{root}/{ref}/revisions/1/upload-grants", headers=setup)
        assert grants.status_code == 200, grants.text
        payloads = {"dsm": b"dsm", "ortho": b"ortho"}
        for grant in grants.json()["grants"]:
            payload = payloads[grant["artifactId"]]
            self.storage.objects[grant["objectKey"]] = ObjectStorageObservation(
                object_key=grant["objectKey"],
                exists=True,
                size_bytes=len(payload),
                sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
                content_type="application/octet-stream",
            )
        sealed = self.client.post(f"{root}/{ref}/revisions/1/seal", headers=setup)
        assert sealed.status_code == 200, sealed.text
        return ref

    def evidence_base(self, name: str) -> str:
        return (
            f"/v1/observation-work-orders/{self.orders[name]}"
            f"/external-reconstruction-submissions/{self.refs[name]}/revisions/1"
        )


def _intent(payload: bytes = b"c1 checkpoint facts") -> dict[str, str]:
    return {
        "targetDsmArtifactId": "dsm",
        "declaredContentDigest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "declaredContentType": "application/octet-stream",
        "independenceBasis": "Customer retained this independent checkpoint export.",
    }


def test_oidc_allowlist_covers_inspection_and_evidence_but_not_worker_routes() -> None:
    assert _EVIDENCE_ROUTES <= _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
    assert _INSPECTION_ROUTES <= _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
    assert _CLOSED_WORKER_ROUTES.isdisjoint(_OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST)


def test_scoped_operator_evidence_flow_and_inspection_read(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    base = fixture.evidence_base("granted")
    declared = fixture.client.post(
        f"{base}/evidence",
        headers={**fixture.headers_a, "Idempotency-Key": "c1-declare"},
        json=_intent(),
    )
    assert declared.status_code == 201, declared.text
    ref = declared.json()["evidenceRef"]
    grant = fixture.client.post(
        f"{base}/evidence/{ref}/upload-grant",
        headers={**fixture.headers_a, "Idempotency-Key": "c1-grant"},
    )
    assert grant.status_code == 200, grant.text
    item = cast(Any, fixture.app).state.external_evidence_store._items[ref]
    fixture.storage.objects[item.object_key] = ObjectStorageObservation(
        object_key=item.object_key,
        exists=True,
        size_bytes=len(b"c1 checkpoint facts"),
        sha256=_intent()["declaredContentDigest"],
        content_type="application/octet-stream",
    )
    sealed = fixture.client.post(
        f"{base}/evidence/{ref}/seal",
        headers={**fixture.headers_a, "Idempotency-Key": "c1-seal"},
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["state"] == "SEALED_BYTE_OBSERVED"
    listed = fixture.client.get(f"{base}/evidence", headers=fixture.headers_a)
    assert listed.status_code == 200, listed.text
    assert [item["evidenceRef"] for item in listed.json()["items"]] == [ref]
    inspection = fixture.client.get(f"{base}/inspection", headers=fixture.headers_a)
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["registrationState"] == "SEALED"
    # Derivative download is allowlisted; without a sealed display it is a
    # non-disclosing 404, never a 403 allowlist refusal.
    download = fixture.client.get(
        f"{base}/display-artifacts/sda-v1-missing/download", headers=fixture.headers_a
    )
    assert download.status_code == 404, download.text


def test_cross_organization_order_is_absent(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    foreign_base = fixture.evidence_base("foreign")
    assert (
        fixture.client.get(f"{foreign_base}/inspection", headers=fixture.headers_a).status_code
        == 404
    )
    assert (
        fixture.client.post(
            f"{foreign_base}/evidence",
            headers={**fixture.headers_a, "Idempotency-Key": "c1-xorg"},
            json=_intent(),
        ).status_code
        == 404
    )
    granted_base = fixture.evidence_base("granted")
    assert (
        fixture.client.get(f"{granted_base}/inspection", headers=fixture.headers_b).status_code
        == 404
    )


def test_same_org_ungranted_site_and_area_are_absent(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    for name in ("ungranted-site", "ungranted-area"):
        base = fixture.evidence_base(name)
        assert (
            fixture.client.get(f"{base}/inspection", headers=fixture.headers_a).status_code == 404
        )
        assert fixture.client.get(f"{base}/evidence", headers=fixture.headers_a).status_code == 404
        assert (
            fixture.client.post(
                f"{base}/evidence",
                headers={**fixture.headers_a, "Idempotency-Key": f"c1-{name}"},
                json=_intent(),
            ).status_code
            == 404
        )


def test_empty_work_area_order_fails_closed_for_area_restricted_principal() -> None:
    """An order with no WorkArea anchor must not satisfy an area-restricted grant.

    ``set() <= grants`` is trivially true, so the scoped-work-order gate must
    treat a missing anchor as fail-closed instead of inheriting the subset rule.
    """
    from types import SimpleNamespace

    from fastapi import HTTPException
    from ksi_core.domains.external.ingress.external_reconstruction import _require_work_order
    from ksi_core.domains.external.quantity.external_analysis_api import ExternalAnalysisFacade
    from ksi_core.external_artifact_inspections import (
        _require_scoped_work_order as inspections_require_scoped,
    )
    from ksi_core.external_evidence import (
        _require_scoped_work_order as evidence_require_scoped,
    )
    from ksi_core.identity.auth import Principal, PrincipalKind, Role

    restricted = Principal(
        principal_id="area-restricted",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"wa-a"}),
    )
    legacy = Principal(
        principal_id="legacy-op",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
    )

    class _StubOrders:
        def __init__(self, order: Any) -> None:
            self._order = order

        def get(self, work_order_id: str, *, organization_id: str) -> Any:
            assert (work_order_id, organization_id) == ("wo-empty", "org-a")
            return self._order

    empty = SimpleNamespace(site_id="site-a", work_area_ids=[])
    assert not ExternalAnalysisFacade._has_work_area_grants(restricted, [])
    assert ExternalAnalysisFacade._has_work_area_grants(legacy, [])
    stub_empty = cast(Any, _StubOrders(empty))
    for require_scoped in (
        evidence_require_scoped,
        inspections_require_scoped,
        _require_work_order,
    ):
        try:
            require_scoped(stub_empty, "wo-empty", restricted)
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("empty WorkArea anchor must fail closed")
        assert require_scoped(stub_empty, "wo-empty", legacy) is empty
        granted = SimpleNamespace(site_id="site-a", work_area_ids=["wa-a"])
        assert require_scoped(cast(Any, _StubOrders(granted)), "wo-empty", restricted) is granted


def test_revoked_subject_is_rejected(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, status="REVOKED")
    assert fixture.client.get("/v1/auth/whoami", headers=fixture.headers_a).status_code == 401
    base = fixture.evidence_base("granted")
    assert fixture.client.get(f"{base}/inspection", headers=fixture.headers_a).status_code == 401


def test_worker_and_lookalike_routes_remain_closed(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    # Mounted worker-only inspection routes refuse the customer principal at
    # the request boundary.
    assert (
        fixture.client.get(
            "/v1/internal/external-validation/inspections", headers=fixture.headers_a
        ).status_code
        == 403
    )
    assert (
        fixture.client.post(
            "/v1/internal/external-validation/inspections/some-request/lease",
            headers={
                **fixture.headers_a,
                "X-KSI-Worker-Instance-Id": "00000000-0000-4000-8000-000000000001",
                "X-KSI-Lease-Acquisition-Id": "00000000-0000-4000-8000-000000000002",
                "X-KSI-Lease-Generation": "0",
            },
        ).status_code
        == 403
    )
    # The evidence-validation worker plane is not assembled without its store,
    # so it is absent rather than allowlisted.
    assert (
        fixture.client.get(
            "/v1/internal/external-validation/evidence-validations", headers=fixture.headers_a
        ).status_code
        == 404
    )
    # FIELD_OPERATOR holds SITES_WRITE, so this 403 comes from the route
    # allowlist rather than the permission gate.
    assert (
        fixture.client.post(
            "/v1/sites", headers=fixture.headers_a, json={"siteId": "x", "name": "x"}
        ).status_code
        == 403
    )
    assert (
        fixture.client.get(
            "/v1/sites/site-a/analyses/result/export", headers=fixture.headers_a
        ).status_code
        == 403
    )
