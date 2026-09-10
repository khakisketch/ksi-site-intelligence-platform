"""Durable, admin-managed organization work roster metadata.

The roster deliberately records *work presentation metadata*, not an identity
provider or permission grant.  Authentication continues to resolve only from
the configured AuthRegistry/OIDC verifier; a roster entry is therefore useful
for assignment selection without widening any principal's authorization.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import Field, ValidationError, field_validator

from ksi_core.api_base import CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identifiers import is_path_safe_identifier


class OrganizationWorkRosterStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class OrganizationWorkRoleHint(StrEnum):
    """Display and assignment eligibility metadata; never an auth role grant."""

    ADMIN = "ADMIN"
    FIELD_OPERATOR = "FIELD_OPERATOR"
    VIEWER = "VIEWER"


def _plain_text(value: str, *, field: str, maximum: int) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > maximum:
        raise ValueError(f"{field} must be nonblank and at most {maximum} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in stripped):
        raise ValueError(f"{field} must not contain control characters")
    return stripped


class OrganizationWorkRosterMember(CamelModel):
    schema_version: Literal["1.0"]
    organization_id: str = Field(min_length=1, max_length=255)
    principal_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=120)
    role_hint: OrganizationWorkRoleHint
    status: OrganizationWorkRosterStatus
    revision: int = Field(ge=1)
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=255)

    @field_validator("organization_id", "principal_id", "updated_by")
    @classmethod
    def _path_safe(cls, value: str) -> str:
        if not is_path_safe_identifier(value):
            raise ValueError("roster identifiers must be path-safe")
        return value

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, value: str) -> str:
        return _plain_text(value, field="displayName", maximum=120)

    @field_validator("updated_at")
    @classmethod
    def _updated_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("updatedAt must be UTC")
        return value


class OrganizationWorkRosterStoreRecoveryError(RuntimeError):
    pass


class OrganizationWorkRosterStore:
    """Append-only roster snapshots, isolated by authenticated organization."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self._journal = journal
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._members: dict[tuple[str, str], OrganizationWorkRosterMember] = {}
        self._idempotency: dict[tuple[str, str, str], tuple[str, OrganizationWorkRosterMember]] = {}
        self._lock = threading.Lock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException:
            journal.close()
            raise

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @staticmethod
    def _key_hash(idempotency_key: str) -> str:
        return "sha256:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint(
        *,
        principal_id: str,
        expected_revision: int,
        display_name: str,
        role_hint: OrganizationWorkRoleHint,
        status: OrganizationWorkRosterStatus,
    ) -> str:
        material = json.dumps(
            {
                "displayName": display_name,
                "expectedRevision": expected_revision,
                "principalId": principal_id,
                "roleHint": role_hint.value,
                "status": status.value,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(material).hexdigest()

    @staticmethod
    def _is_digest(value: object) -> bool:
        return (
            isinstance(value, str)
            and value.startswith("sha256:")
            and len(value) == 71
            and all(char in "0123456789abcdef" for char in value[7:])
        )

    def _apply(self, raw: dict[str, Any]) -> None:
        try:
            if set(raw) != {"kind", "ts", "actor", "member", "idempotency"}:
                raise ValueError("roster journal event keys are not exact")
            if raw["kind"] != "organization-work-roster-member-upserted":
                raise ValueError("roster journal event kind is invalid")
            if not isinstance(raw["member"], dict) or raw["member"].get("schemaVersion") != "1.0":
                raise ValueError("roster member schemaVersion is invalid")
            member = OrganizationWorkRosterMember.model_validate(raw["member"])
            if raw["actor"] != member.updated_by or raw["ts"] != iso_utc(member.updated_at):
                raise ValueError("roster event audit does not match member snapshot")
            binding = raw["idempotency"]
            if not isinstance(binding, dict) or set(binding) != {"keyHash", "fingerprint"}:
                raise ValueError("roster idempotency binding is malformed")
            key_hash, fingerprint = binding["keyHash"], binding["fingerprint"]
            if not self._is_digest(key_hash) or not self._is_digest(fingerprint):
                raise ValueError("roster idempotency binding is malformed")
            key = (member.organization_id, member.principal_id)
            current = self._members.get(key)
            if member.revision != (1 if current is None else current.revision + 1):
                raise ValueError("roster revision lineage is invalid")
            expected_fingerprint = self._fingerprint(
                principal_id=member.principal_id,
                expected_revision=member.revision - 1,
                display_name=member.display_name,
                role_hint=member.role_hint,
                status=member.status,
            )
            if fingerprint != expected_fingerprint:
                raise ValueError("roster idempotency fingerprint is invalid")
            idem_key = (member.organization_id, raw["actor"], key_hash)
            if idem_key in self._idempotency:
                raise ValueError("duplicate roster idempotency key")
            self._members[key] = member
            self._idempotency[idem_key] = (fingerprint, member)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise OrganizationWorkRosterStoreRecoveryError(
                f"organization work roster journal replay failed: {exc}"
            ) from exc

    def put_member(
        self,
        *,
        organization_id: str,
        principal_id: str,
        expected_revision: int,
        display_name: str,
        role_hint: OrganizationWorkRoleHint,
        status: OrganizationWorkRosterStatus,
        actor: str,
        idempotency_key: str,
        now: datetime,
    ) -> OrganizationWorkRosterMember:
        if not all(
            is_path_safe_identifier(value) for value in (organization_id, principal_id, actor)
        ):
            raise ValueError("roster identifiers must be path-safe")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expectedRevision must be a nonnegative integer")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 255:
            raise ValueError("Idempotency-Key must be a nonblank value up to 255 characters")
        if now.tzinfo is None:
            raise ValueError("roster timestamp must be timezone-aware")
        normalized_display_name = _plain_text(display_name, field="displayName", maximum=120)
        key_hash = self._key_hash(idempotency_key)
        fingerprint = self._fingerprint(
            principal_id=principal_id,
            expected_revision=expected_revision,
            display_name=normalized_display_name,
            role_hint=role_hint,
            status=status,
        )
        with self._coordinator.mutation(), self._lock:
            prior = self._idempotency.get((organization_id, actor, key_hash))
            if prior is not None:
                prior_fingerprint, member = prior
                if prior_fingerprint != fingerprint:
                    raise RuntimeError("ROSTER_IDEMPOTENCY_CONFLICT")
                return member.model_copy(deep=True)
            current = self._members.get((organization_id, principal_id))
            actual_revision = 0 if current is None else current.revision
            if actual_revision != expected_revision:
                raise RuntimeError("ROSTER_REVISION_CONFLICT")
            if (
                current is None
                and sum(1 for member_org, _ in self._members if member_org == organization_id)
                >= 100
            ):
                # The read API is deliberately unpaginated and capped at 100;
                # reject a 101st creation rather than make a managed identity
                # disappear from an administrator's view.
                raise RuntimeError("ROSTER_CAP_REACHED")
            member = OrganizationWorkRosterMember(
                schema_version="1.0",
                organization_id=organization_id,
                principal_id=principal_id,
                display_name=normalized_display_name,
                role_hint=role_hint,
                status=status,
                revision=actual_revision + 1,
                updated_at=now.astimezone(UTC),
                updated_by=actor,
            )
            self._journal.append(
                {
                    "kind": "organization-work-roster-member-upserted",
                    "ts": iso_utc(member.updated_at),
                    "actor": actor,
                    "member": member.model_dump(by_alias=True, mode="json"),
                    "idempotency": {"keyHash": key_hash, "fingerprint": fingerprint},
                }
            )
            self._apply(
                {
                    "kind": "organization-work-roster-member-upserted",
                    "ts": iso_utc(member.updated_at),
                    "actor": actor,
                    "member": member.model_dump(by_alias=True, mode="json"),
                    "idempotency": {"keyHash": key_hash, "fingerprint": fingerprint},
                }
            )
            return member.model_copy(deep=True)

    def get_member(
        self, principal_id: str, *, organization_id: str
    ) -> OrganizationWorkRosterMember | None:
        with self._lock:
            member = self._members.get((organization_id, principal_id))
            return member.model_copy(deep=True) if member is not None else None

    def list_members(
        self,
        *,
        organization_id: str,
        include_inactive: bool,
        search: str | None = None,
        limit: int = 100,
    ) -> list[OrganizationWorkRosterMember]:
        if not is_path_safe_identifier(organization_id):
            raise ValueError("organizationId must be path-safe")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        needle = _plain_text(search, field="search", maximum=120).casefold() if search else None
        with self._lock:
            members = [
                member.model_copy(deep=True)
                for (member_org, _), member in self._members.items()
                if member_org == organization_id
                and (include_inactive or member.status is OrganizationWorkRosterStatus.ACTIVE)
                and (
                    needle is None
                    or needle in member.principal_id.casefold()
                    or needle in member.display_name.casefold()
                )
            ]
        return sorted(members, key=lambda item: (item.display_name.casefold(), item.principal_id))[
            :limit
        ]

    def is_assignable_member(self, principal_id: str, *, organization_id: str) -> bool:
        with self._lock:
            member = self._members.get((organization_id, principal_id))
            return bool(
                member is not None
                and member.status is OrganizationWorkRosterStatus.ACTIVE
                and member.role_hint
                in {OrganizationWorkRoleHint.ADMIN, OrganizationWorkRoleHint.FIELD_OPERATOR}
            )


class OrganizationWorkRosterListResponse(CamelModel):
    members: list[OrganizationWorkRosterMember]


class OrganizationWorkRosterUpsertRequest(CamelModel):
    expected_revision: int = Field(ge=0)
    display_name: str = Field(min_length=1, max_length=120)
    role_hint: OrganizationWorkRoleHint
    status: OrganizationWorkRosterStatus

    @field_validator("display_name")
    @classmethod
    def _plain_display_name(cls, value: str) -> str:
        return _plain_text(value, field="displayName", maximum=120)


def _require_human(principal: Principal) -> Principal:
    if principal.kind is not PrincipalKind.OPERATOR:
        raise HTTPException(status_code=403, detail="HUMAN_AUTHORITY_REQUIRED")
    return principal


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, JournalSealedError):
        return HTTPException(status_code=503, detail="DURABLE_JOURNAL_UNAVAILABLE")
    if str(exc) == "ROSTER_IDEMPOTENCY_CONFLICT":
        return HTTPException(
            status_code=409, detail="Idempotency-Key가 다른 roster 요청에 이미 사용됐다"
        )
    if str(exc) == "ROSTER_REVISION_CONFLICT":
        return HTTPException(status_code=409, detail="expectedRevision 이 현재 revision 과 다르다")
    if str(exc) == "ROSTER_CAP_REACHED":
        return HTTPException(
            status_code=409, detail="organization work roster 최대 100명에 도달했다"
        )
    return HTTPException(status_code=422, detail=str(exc))


def build_organization_work_roster_router(store: OrganizationWorkRosterStore) -> APIRouter:
    """Mount the bounded organization roster without exposing identity records."""

    router = APIRouter(tags=["organization-work-roster"])

    @router.get("/v1/organization-work-roster", response_model=OrganizationWorkRosterListResponse)
    def list_roster(
        include_inactive: bool = Query(default=False, alias="includeInactive"),  # noqa: B008
        search: str | None = Query(default=None, max_length=120),  # noqa: B008
        limit: int = Query(default=100, ge=1, le=100),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008,E501
    ) -> OrganizationWorkRosterListResponse:
        _require_human(principal)
        # The permission dependency cannot express optional admin scope; use
        # the role-derived permission check here only for the expanded list.
        from ksi_core.auth import principal_permissions

        if include_inactive and Permission.ORGANIZATION_MEMBERS_MANAGE not in principal_permissions(
            principal
        ):
            raise HTTPException(status_code=403, detail="권한이 부족하다")
        try:
            return OrganizationWorkRosterListResponse(
                members=store.list_members(
                    organization_id=principal.organization_id,
                    include_inactive=include_inactive,
                    search=search,
                    limit=limit,
                )
            )
        except ValueError as exc:
            raise _http_error(exc) from exc

    @router.put(
        "/v1/organization-work-roster/{principal_id}",
        response_model=OrganizationWorkRosterMember,
    )
    def upsert_roster_member(
        principal_id: str,
        request: OrganizationWorkRosterUpsertRequest,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.ORGANIZATION_MEMBERS_MANAGE)),  # noqa: B008
    ) -> OrganizationWorkRosterMember:
        _require_human(principal)
        try:
            return store.put_member(
                organization_id=principal.organization_id,
                principal_id=principal_id,
                expected_revision=request.expected_revision,
                display_name=request.display_name,
                role_hint=request.role_hint,
                status=request.status,
                actor=principal.principal_id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    return router
