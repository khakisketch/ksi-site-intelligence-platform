"""Protected issuer-subject to KSI principal mappings for human OIDC auth.

## 버전별 문법 (F-01 C3)

- ``oidc-subject-registry.v1``: 기존 문법 그대로 — 두 scope 필드가 **필수
  배열**이고 capability 표현이 없다.
- ``oidc-subject-registry.v2``: ``capabilities`` 필수 + 두 scope 필드 **필수**
  (명시 ``null`` 또는 배열). 명시 ``null`` 은 "KSI 가 별도로 발급한 자기 조직
  전체 범위"라는 결정이고, 배열은 명시 목록(빈 배열 포함)이다.

필드 누락·invalid 는 어느 버전에서도 **로드 실패**다 — 누락이 ``null``(전체
허용)로 승격되는 fail-open 경로를 만들지 않는다. v2 파싱 실패 후 v1 재시도도
하지 않는다(버전이 문법을 결정한다). 파싱에 성공한 매핑만
``Principal.registry_scoped`` 를 세워 검토된 route matrix 밖의 미검토 route 로
새지 않게 한다. capability 는 role/permission 과 독립이며, v1 에는 존재하지
않는다.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import Capability, Principal, PrincipalKind, Role

_V1_VERSION = "oidc-subject-registry.v1"
_V2_VERSION = "oidc-subject-registry.v2"
_MAX_FILE_BYTES = 64 * 1024
_MAX_SUBJECTS = 512
_MAX_TEXT_LENGTH = 2_048
_TOP_FIELDS = {"version", "subjects"}
_V1_SUBJECT_FIELDS = {
    "issuer",
    "subject",
    "principalId",
    "organizationId",
    "role",
    "status",
    "allowedSiteIds",
    "allowedWorkAreaIds",
}
_V2_SUBJECT_FIELDS = _V1_SUBJECT_FIELDS | {"capabilities"}


@dataclass(frozen=True, slots=True)
class OidcSubjectMapping:
    issuer: str
    subject: str
    principal_id: str
    organization_id: str
    role: Role
    status: str
    # v2 명시 null = 자기 조직 전체. v1 은 항상 frozenset(빈 집합 = 접근 없음).
    allowed_site_ids: frozenset[str] | None
    allowed_work_area_ids: frozenset[str] | None
    # v1 매핑은 빈 집합이다(v1 에는 capability 표현이 없다).
    capabilities: frozenset[Capability] = frozenset()

    def principal(self) -> Principal | None:
        if self.status != "ACTIVE":
            return None
        return Principal(
            principal_id=self.principal_id,
            organization_id=self.organization_id,
            kind=PrincipalKind.OPERATOR,
            role=self.role,
            device_id=None,
            allowed_site_ids=self.allowed_site_ids,
            allowed_work_area_ids=self.allowed_work_area_ids,
            registry_scoped=True,
            capabilities=self.capabilities,
        )


@dataclass(frozen=True, slots=True)
class OidcSubjectRegistry:
    _mappings: dict[tuple[str, str], OidcSubjectMapping]

    @classmethod
    def from_document(
        cls, document: object, *, expected_issuer: str
    ) -> OidcSubjectRegistry:
        body = _mapping(document, _TOP_FIELDS)
        version = _text(body["version"])
        if version == _V1_VERSION:
            subject_fields = _V1_SUBJECT_FIELDS
        elif version == _V2_VERSION:
            subject_fields = _V2_SUBJECT_FIELDS
        else:
            # 미지원 버전은 재시도 없이 거부한다 — v2 문서를 v1 문법으로
            # 재해석하거나 그 반대의 fallback 을 만들지 않는다.
            raise ValueError("unsupported OIDC subject registry version")
        if not expected_issuer or len(expected_issuer) > _MAX_TEXT_LENGTH:
            raise ValueError("expected OIDC issuer is invalid")
        entries = body["subjects"]
        if not isinstance(entries, list) or not 0 < len(entries) <= _MAX_SUBJECTS:
            raise ValueError("OIDC subjects must be a bounded non-empty array")

        mappings: dict[tuple[str, str], OidcSubjectMapping] = {}
        principal_ids: set[str] = set()
        for entry in entries:
            row = _mapping(entry, subject_fields)
            issuer = _text(row["issuer"])
            subject = _text(row["subject"])
            if issuer != expected_issuer:
                raise ValueError("OIDC subject registry issuer does not match configured issuer")
            key = (issuer, subject)
            if key in mappings:
                raise ValueError("duplicate OIDC (issuer, subject) mapping")
            principal_id = _safe_id(row["principalId"], "principalId")
            if principal_id in principal_ids:
                raise ValueError("duplicate OIDC principalId mapping")
            principal_ids.add(principal_id)
            organization_id = _safe_id(row["organizationId"], "organizationId")
            try:
                role = Role(_text(row["role"]))
            except ValueError as exc:
                raise ValueError("OIDC subject role is invalid") from exc
            status = _text(row["status"])
            if status not in {"ACTIVE", "REVOKED"}:
                raise ValueError("OIDC subject status must be ACTIVE or REVOKED")
            if version == _V2_VERSION:
                allowed_site_ids = _safe_id_set_or_none(
                    row["allowedSiteIds"], "allowedSiteIds"
                )
                allowed_work_area_ids = _safe_id_set_or_none(
                    row["allowedWorkAreaIds"], "allowedWorkAreaIds"
                )
                capabilities = _capabilities(row["capabilities"])
            else:
                allowed_site_ids = _safe_id_set(row["allowedSiteIds"], "allowedSiteIds")
                allowed_work_area_ids = _safe_id_set(
                    row["allowedWorkAreaIds"], "allowedWorkAreaIds"
                )
                capabilities = frozenset()
            mappings[key] = OidcSubjectMapping(
                issuer=issuer,
                subject=subject,
                principal_id=principal_id,
                organization_id=organization_id,
                role=role,
                status=status,
                allowed_site_ids=allowed_site_ids,
                allowed_work_area_ids=allowed_work_area_ids,
                capabilities=capabilities,
            )
        return cls(mappings)

    def resolve(self, issuer: str, subject: str) -> Principal | None:
        mapping = self._mappings.get((issuer, subject))
        return mapping.principal() if mapping is not None else None

    def principal_by_id(self, principal_id: str) -> Principal | None:
        """Trusted local lookup for boot-loaded mapped identities.

        Only an ACTIVE mapping yields a principal; a REVOKED mapping returns
        ``None``. Revocation is therefore applied at the next Core restart,
        consistent with the other boot-loaded Core authorities.
        """
        for mapping in self._mappings.values():
            if mapping.principal_id == principal_id:
                return mapping.principal()
        return None

    @property
    def principal_ids(self) -> frozenset[str]:
        return frozenset(mapping.principal_id for mapping in self._mappings.values())


def load_oidc_subject_registry(path: Path, *, expected_issuer: str) -> OidcSubjectRegistry:
    """Load a private, bounded registry without following symlinks."""
    raw = _read_private(path)
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("OIDC subject registry JSON is invalid") from exc
    try:
        return OidcSubjectRegistry.from_document(document, expected_issuer=expected_issuer)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("OIDC subject registry contents are invalid") from exc


def _read_private(path: Path) -> bytes:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise ValueError("OIDC subject registry path must be absolute and normalized")
    directory_fd = -1
    file_fd = -1
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        directory_fd = os.open(path.anchor, directory_flags)
        parent = os.fstat(directory_fd)
        for component in path.parts[1:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            try:
                child = os.fstat(next_fd)
                _validate_ancestor(parent, child)
            except BaseException:
                os.close(next_fd)
                raise
            os.close(directory_fd)
            directory_fd = next_fd
            parent = child
        file_fd = os.open(path.name, file_flags, dir_fd=directory_fd)
        before = os.fstat(file_fd)
        _validate_ancestor(parent, before)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_FILE_BYTES
        ):
            raise ValueError("OIDC subject registry file must be private and bounded")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(file_fd, min(8_192, _MAX_FILE_BYTES - size + 1))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > _MAX_FILE_BYTES:
                raise ValueError("OIDC subject registry exceeds size limit")
        after = os.fstat(file_fd)
        content = b"".join(chunks)
        if len(content) != before.st_size or _stable_metadata(after) != _stable_metadata(before):
            raise ValueError("OIDC subject registry changed while being read")
        return content
    except OSError as exc:
        raise ValueError("OIDC subject registry file is unavailable or unsafe") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _validate_ancestor(parent: os.stat_result, child: os.stat_result) -> None:
    mode = parent.st_mode
    sticky_protects_child = bool(stat.S_ISVTX & mode) and (
        parent.st_uid == os.geteuid() or child.st_uid == os.geteuid()
    )
    if (
        not stat.S_ISDIR(mode)
        or parent.st_uid not in {0, os.geteuid()}
        or (stat.S_IMODE(mode) & 0o022 and not sticky_protects_child)
    ):
        raise ValueError("OIDC subject registry path has an unsafe ancestor")


def _stable_metadata(node: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        node.st_size,
        node.st_mtime_ns,
        node.st_ctime_ns,
        node.st_mode,
        node.st_uid,
        node.st_gid,
        node.st_nlink,
    )


def _mapping(value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("OIDC subject registry object has missing or unknown fields")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT_LENGTH:
        raise ValueError("OIDC subject registry text value is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("OIDC subject registry text is not valid UTF-8") from exc
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("OIDC subject registry text contains control characters")
    return value


def _safe_id(value: object, name: str) -> str:
    text = _text(value)
    if not is_path_safe_identifier(text):
        raise ValueError(f"OIDC {name} must be a path-safe identifier")
    return text


def _safe_id_set(value: object, name: str) -> frozenset[str]:
    if not isinstance(value, list) or len(value) > _MAX_SUBJECTS:
        raise ValueError(f"OIDC {name} must be a bounded array")
    values = [_safe_id(item, name) for item in value]
    if len(values) != len(set(values)):
        raise ValueError(f"OIDC {name} contains duplicate identifiers")
    return frozenset(values)


def _safe_id_set_or_none(value: object, name: str) -> frozenset[str] | None:
    """v2 전용 — **명시 ``null``** 만 "자기 조직 전체"이고, 그 밖의 값은 배열이다.

    호출 전에 ``_mapping`` 이 필드 존재를 강제하므로, 여기서 ``None`` 은 항상
    "키가 없어서"가 아니라 "JSON null 이 명시됐다"는 뜻이다. 그 구분이
    fail-open 방지의 핵심이다(문서 docstring).
    """
    if value is None:
        return None
    return _safe_id_set(value, name)


def _capabilities(value: object) -> frozenset[Capability]:
    """v2 ``capabilities`` — 알려진 capability 의 중복 없는 배열만 허용한다.

    빈 배열은 유효하다(발급 없음). ``null``·누락·미지 값은 거부한다 — 미지
    capability 를 조용히 무시하면 발급자와 소비자의 해석이 갈라진다.
    """
    if not isinstance(value, list) or len(value) > len(Capability):
        raise ValueError("OIDC capabilities must be a bounded array")
    parsed: list[Capability] = []
    for item in value:
        try:
            parsed.append(Capability(_text(item)))
        except ValueError as exc:
            raise ValueError("OIDC capability is invalid") from exc
    if len(parsed) != len(set(parsed)):
        raise ValueError("OIDC capabilities contains duplicate identifiers")
    return frozenset(parsed)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value!r}")


__all__ = ["OidcSubjectMapping", "OidcSubjectRegistry", "load_oidc_subject_registry"]
