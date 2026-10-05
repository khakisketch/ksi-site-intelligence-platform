"""Customer HTTP-only consumer for the KSI V2 external analysis flow.

This module is intentionally dependency-light: it imports only the Python
standard library plus ``httpx``. It never imports KSI packages, test stores,
or fixtures, so it can be copied onto a customer workstation as-is.

Operator setup (done separately, never by this class):

  * The operator registers the Site and WorkArea and tells the customer the
    ``site_id`` / ``work_area_id``.
  * The operator provisions a ``FIELD_OPERATOR`` OIDC subject whose grants
    cover exactly that Site/WorkArea and gives the customer its signed JWT.
  * The customer passes that JWT via the ``token`` argument or the
    ``KSI_CUSTOMER_TOKEN`` environment variable. ADMIN or worker credentials
    must never be placed here; this class sends exactly one credential, the
    caller-supplied field-operator token, on Core API calls only.

Safety properties:

  * The bearer token is attached to Core API requests only. Object-byte
    uploads use a separate anonymous client, so a storage grant URL can never
    receive the customer credential (no unsafe grant forwarding).
  * Nothing in this module prints tokens or upload URLs.
  * Creation routes always send an explicit ``Idempotency-Key`` supplied by
    the caller, so retries are durable server-side replays, not duplicates.
  * JSON declarations (reconstruction submissions, evidence intents, analysis
    selectors) are supplied by the caller with explicit known metadata. This
    class never invents capture times, producer identities, or vertical
    references.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx


class CustomerHttpError(RuntimeError):
    """A Core request failed; carries the HTTP status and server detail."""

    def __init__(self, method: str, path: str, status: int, detail: str) -> None:
        super().__init__(f"{method} {path} -> {status}: {detail}")
        self.method = method
        self.path = path
        self.status = status
        self.detail = detail


class CustomerV2Client:
    """Reusable HTTP-only driver for the customer side of the V2 flow."""

    def __init__(
        self,
        base_url: str,
        *,
        site_id: str,
        work_area_id: str,
        token: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        resolved = token if token is not None else os.environ.get("KSI_CUSTOMER_TOKEN")
        if resolved is None or not resolved.strip():
            raise ValueError(
                "a FIELD_OPERATOR OIDC token is required (argument or KSI_CUSTOMER_TOKEN)"
            )
        self._base_url = base_url.rstrip("/")
        self._site_id = site_id
        self._work_area_id = work_area_id
        self._api = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": "Bearer " + resolved.strip()},
            timeout=timeout_seconds,
        )
        # Anonymous client for direct object-byte PUTs: never carries auth.
        self._objects = httpx.Client(timeout=timeout_seconds)

    @property
    def site_id(self) -> str:
        return self._site_id

    @property
    def work_area_id(self) -> str:
        return self._work_area_id

    def close(self) -> None:
        self._api.close()
        self._objects.close()

    def __enter__(self) -> CustomerV2Client:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    # -- internals ------------------------------------------------------
    def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        idempotency_key: str | None = None,
        params: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Any:
        headers: dict[str, str] = {}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        response = self._api.request(
            method, path, json=json_body, headers=headers or None, params=params
        )
        if response.status_code not in expected:
            raise CustomerHttpError(method, path, response.status_code, response.text[:500])
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # -- work orders ----------------------------------------------------
    def create_work_order(self, name: str, *, idempotency_key: str) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/sites/{self._site_id}/observation-work-orders",
            json_body={
                "name": name,
                "workAreaIds": [self._work_area_id],
                "executionMode": "EXTERNAL_RECONSTRUCTION",
            },
            idempotency_key=idempotency_key,
            expected=(201,),
        )

    def get_work_order(self, work_order_id: str) -> dict[str, Any]:
        return self._call("GET", f"/v1/observation-work-orders/{work_order_id}")

    def get_registration_context(self, work_order_id: str) -> dict[str, Any]:
        return self._call(
            "GET",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-context",
        )

    # -- V2 reconstruction registration ----------------------------------
    def register_submission_v2(
        self, work_order_id: str, submission: dict[str, Any]
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions-v2",
            json_body=submission,
            expected=(201,),
        )

    def get_revision(
        self, work_order_id: str, submission_ref: str, *, revision: int = 1
    ) -> dict[str, Any]:
        return self._call(
            "GET",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
            f"{submission_ref}/revisions/{revision}",
        )

    def request_upload_grants(
        self, work_order_id: str, submission_ref: str, *, revision: int = 1
    ) -> list[dict[str, Any]]:
        body = self._call(
            "POST",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
            f"{submission_ref}/revisions/{revision}/upload-grants",
        )
        return list(body["grants"])

    def put_object_bytes(
        self,
        upload_url: str,
        data: bytes,
        *,
        content_type: str,
        required_headers: dict[str, str] | None = None,
    ) -> None:
        """PUT bytes to a granted URL without any credential headers.

        The exact ``requiredHeaders`` from the grant (e.g. the bound
        ``x-amz-checksum-sha256``) are forwarded unchanged so the server can
        enforce the digest/size binding. Credential headers are never
        accepted here: ``Authorization``, ``Cookie`` and proxy credential
        headers are rejected instead of forwarded, and this client never
        attaches its bearer token to object uploads.
        """
        headers: dict[str, str] = {}
        for name, value in (required_headers or {}).items():
            lowered = name.lower()
            if lowered in (
                "authorization",
                "cookie",
                "proxy-authorization",
                "proxy-authenticate",
            ):
                raise ValueError(f"refusing to forward credential header {name!r}")
            headers[name] = value
        headers.setdefault("Content-Type", content_type)
        response = self._objects.put(upload_url, content=data, headers=headers)
        if response.status_code not in (200, 201, 204):
            raise CustomerHttpError("PUT", "<granted-object-url>", response.status_code, "")

    def seal_revision(
        self, work_order_id: str, submission_ref: str, *, revision: int = 1
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
            f"{submission_ref}/revisions/{revision}/seal",
        )

    def get_inspection(
        self, work_order_id: str, submission_ref: str, *, revision: int = 1
    ) -> dict[str, Any]:
        return self._call(
            "GET",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
            f"{submission_ref}/revisions/{revision}/inspection",
        )

    # -- evidence remediation --------------------------------------------
    def declare_evidence(
        self,
        work_order_id: str,
        submission_ref: str,
        intent: dict[str, Any],
        *,
        revision: int = 1,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
            f"{submission_ref}/revisions/{revision}/evidence",
            json_body=intent,
            idempotency_key=idempotency_key,
            expected=(201,),
        )

    def list_evidence(
        self, work_order_id: str, submission_ref: str, *, revision: int = 1
    ) -> list[dict[str, Any]]:
        body = self._call(
            "GET",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
            f"{submission_ref}/revisions/{revision}/evidence",
        )
        return list(body.get("items", []))

    def grant_evidence_upload(
        self,
        work_order_id: str,
        submission_ref: str,
        evidence_ref: str,
        *,
        revision: int = 1,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
            f"{submission_ref}/revisions/{revision}/evidence/{evidence_ref}/upload-grant",
            idempotency_key=idempotency_key,
        )

    def seal_evidence(
        self,
        work_order_id: str,
        submission_ref: str,
        evidence_ref: str,
        *,
        revision: int = 1,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
            f"{submission_ref}/revisions/{revision}/evidence/{evidence_ref}/seal",
            idempotency_key=idempotency_key,
        )

    # -- V2 analysis ------------------------------------------------------
    def list_observation_options(self) -> dict[str, Any]:
        return self._call("GET", f"/v1/sites/{self._site_id}/analysis-observations")

    def create_analysis(
        self,
        baseline: dict[str, Any],
        current: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/v2/sites/{self._site_id}/work-areas/{self._work_area_id}/analyses",
            json_body={"baseline": baseline, "current": current},
            idempotency_key=idempotency_key,
            expected=(202,),
        )

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        return self._call("GET", f"/v2/sites/{self._site_id}/analyses/{analysis_id}")

    def get_analysis_evidence(self, analysis_id: str) -> dict[str, Any]:
        return self._call("GET", f"/v2/sites/{self._site_id}/analyses/{analysis_id}/evidence")

    def get_coverage_range(
        self, analysis_id: str, *, start: int, end: int
    ) -> tuple[bytes, dict[str, str]]:
        """Read existing digest-bound coverage bytes, bounded to one 64-KiB range."""
        if type(start) is not int or type(end) is not int or not 0 <= start <= end:
            raise ValueError("coverage requires nonnegative inclusive integer bounds")
        if end - start + 1 > 65_536:
            raise ValueError("coverage range must be at most 65536 bytes")
        path = f"/v2/sites/{self._site_id}/analyses/{analysis_id}/coverage"
        response = self._api.get(path, headers={"Range": f"bytes={start}-{end}"})
        if response.status_code != 206:
            raise CustomerHttpError("GET", path, response.status_code, "")
        metadata = {
            name: response.headers[name]
            for name in ("content-range", "content-length", "x-ksi-coverage-digest")
        }
        return response.content, metadata

    def wait_for_analysis(
        self, analysis_id: str, *, timeout_seconds: float = 120.0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            view = self.get_analysis(analysis_id)
            if view.get("executionState") in ("COMPLETED", "FAILED"):
                return view
            if view.get("suitabilityState") in (
                "BLOCKED",
                "REMEDIATION_REQUIRED",
                "REASSESSMENT_REQUIRED",
            ):
                return view
            if time.monotonic() > deadline:
                raise TimeoutError(f"analysis {analysis_id} did not finish in time")
            time.sleep(0.2)

    # -- human reviews ------------------------------------------------------
    def get_review_target(self, analysis_id: str) -> dict[str, Any]:
        return self._call("GET", f"/v2/sites/{self._site_id}/analyses/{analysis_id}/review-target")

    def post_review(
        self,
        analysis_id: str,
        target: dict[str, Any],
        *,
        decision: str,
        comment: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if decision not in ("ACKNOWLEDGED", "NEEDS_FOLLOW_UP"):
            raise ValueError("decision must be ACKNOWLEDGED or NEEDS_FOLLOW_UP")
        return self._call(
            "POST",
            f"/v2/sites/{self._site_id}/analyses/{analysis_id}/reviews",
            json_body={"target": target, "decision": decision, "comment": comment},
            idempotency_key=idempotency_key,
            expected=(201,),
        )

    def list_reviews(
        self, analysis_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be within 1..50")
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._call(
            "GET",
            f"/v2/sites/{self._site_id}/analyses/{analysis_id}/reviews",
            params=params,
        )
