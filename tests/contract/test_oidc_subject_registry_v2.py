"""OIDC subject registry v2 — 명시 null 과 누락/invalid 의 fail-closed 구분 (F-01 C3).

``allowedSiteIds: null`` 은 KSI 가 **별도로 발급한 자기 조직 전체 Site scope**
이고, 명시 배열은 최소권한 목록이다. 필드 누락·invalid·구버전 fallback 이
``null``(전체 허용)로 승격되는 경로가 없어야 한다. v1 은 기존 배열-전용 문법
그대로이며, v2 실패 후 v1 재시도가 일어나지 않는다.

schema(``contracts/schemas/oidc-subject-registry.v2.json``)는 같은 문법을
문서화하되 semantics(issuer 일치·중복·파일 보호)를 대체하지 않는다 — 이 파일이
그 경계를 corpus 로 고정한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from ksi_core.composition.runtime_config import _parse_principal_tokens
from ksi_core.identity.auth import Capability
from ksi_core.identity.oidc_subject_registry import (
    OidcSubjectRegistry,
    load_oidc_subject_registry,
)

ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = ROOT / "contracts" / "schemas" / "oidc-subject-registry.v2.json"

_ISSUER = "https://issuer.example.test"


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "issuer": _ISSUER,
        "subject": "provider-subject-1",
        "principalId": "oidc-user-1",
        "organizationId": "org-1",
        "role": "FIELD_OPERATOR",
        "status": "ACTIVE",
        "allowedSiteIds": ["site-1"],
        "allowedWorkAreaIds": ["area-1"],
        "capabilities": [],
    }
    row.update(overrides)
    return row


def _document(*rows: dict[str, Any], version: str = "oidc-subject-registry.v2") -> dict[str, Any]:
    return {"version": version, "subjects": list(rows) if rows else [_row()]}


def _v1_row(**overrides: Any) -> dict[str, Any]:
    row = _row(**overrides)
    del row["capabilities"]
    return row


# ── 1. 파싱 결과 동등성 ────────────────────────────────────────────────


def test_v1_and_v2_array_only_produce_same_scope_and_role() -> None:
    v1 = OidcSubjectRegistry.from_document(
        _document(_v1_row(), version="oidc-subject-registry.v1"), expected_issuer=_ISSUER
    )
    v2 = OidcSubjectRegistry.from_document(_document(_row()), expected_issuer=_ISSUER)

    first = v1.resolve(_ISSUER, "provider-subject-1")
    second = v2.resolve(_ISSUER, "provider-subject-1")
    assert first is not None and second is not None
    assert (first.allowed_site_ids, first.allowed_work_area_ids) == (
        second.allowed_site_ids,
        second.allowed_work_area_ids,
    )
    assert (first.organization_id, first.role) == (second.organization_id, second.role)
    # v1/v2 배열-전용 발급 모두 검토된 route matrix 로 묶인다 — marker 는
    # "누락/null 의 우회"를 막는 장치이지 v1 의 의미를 바꾸지 않는다.
    assert first.registry_scoped is True and second.registry_scoped is True
    assert first.capabilities == frozenset() and second.capabilities == frozenset()


def test_v2_explicit_null_means_org_wide_scope_distinct_from_empty() -> None:
    registry = OidcSubjectRegistry.from_document(
        _document(
            _row(allowedSiteIds=None, allowedWorkAreaIds=None, capabilities=["SITE_BOOTSTRAP"]),
            _row(
                subject="subject-empty",
                principalId="user-empty",
                allowedSiteIds=[],
                allowedWorkAreaIds=[],
            ),
            _row(
                subject="subject-one",
                principalId="user-one",
                allowedSiteIds=["site-9"],
                allowedWorkAreaIds=["area-9"],
            ),
        ),
        expected_issuer=_ISSUER,
    )

    org_wide = registry.resolve(_ISSUER, "provider-subject-1")
    assert org_wide is not None
    assert org_wide.allowed_site_ids is None and org_wide.allowed_work_area_ids is None
    assert org_wide.capabilities == frozenset({Capability.SITE_BOOTSTRAP})

    empty = registry.resolve(_ISSUER, "subject-empty")
    assert empty is not None
    assert empty.allowed_site_ids == frozenset()
    assert empty.allowed_work_area_ids == frozenset()

    one = registry.resolve(_ISSUER, "subject-one")
    assert one is not None
    assert one.allowed_site_ids == frozenset({"site-9"})


# ── 2. 누락·null·invalid 는 fail-closed ────────────────────────────────


@pytest.mark.parametrize(
    "missing", ["capabilities", "allowedSiteIds", "allowedWorkAreaIds", "version", "status"]
)
def test_v2_missing_required_field_is_rejected(missing: str) -> None:
    row = _row()
    document: dict[str, Any] = {"version": "oidc-subject-registry.v2", "subjects": [row]}
    if missing == "version":
        del document["version"]
    else:
        del row[missing]
    with pytest.raises(ValueError):
        OidcSubjectRegistry.from_document(document, expected_issuer=_ISSUER)


def test_v1_rejects_capabilities_and_null_scopes() -> None:
    # v1 은 capability 표현이 없다 — 필드를 실으면 unknown field 로 거부된다.
    with pytest.raises(ValueError):
        OidcSubjectRegistry.from_document(
            _document(_row(), version="oidc-subject-registry.v1"), expected_issuer=_ISSUER
        )
    # v1 의 null scope 는 없는 문법이고, null→배열 빈 값으로도 승격되지 않는다.
    for field in ("allowedSiteIds", "allowedWorkAreaIds"):
        with pytest.raises(ValueError):
            OidcSubjectRegistry.from_document(
                _document(_v1_row(**{field: None}), version="oidc-subject-registry.v1"),
                expected_issuer=_ISSUER,
            )


@pytest.mark.parametrize(
    "capabilities",
    [
        None,
        {},
        "SITE_BOOTSTRAP",
        ["SITE_BOOTSTRAP", "SITE_BOOTSTRAP"],
        ["SITE_BOOTSTRAP", "UNKNOWN_CAPABILITY"],
        [None],
        ["SITE_BOOTSTRAP\n"],
    ],
)
def test_v2_capabilities_reject_null_unknown_duplicate_and_non_string(
    capabilities: object,
) -> None:
    with pytest.raises(ValueError):
        OidcSubjectRegistry.from_document(
            _document(_row(capabilities=capabilities)), expected_issuer=_ISSUER
        )


@pytest.mark.parametrize("value", ["site-1", 3, {"siteId": "site-1"}, [None], [3], ["a/b"]])
def test_v2_scope_rejects_non_array_non_id_shapes(value: object) -> None:
    for field in ("allowedSiteIds", "allowedWorkAreaIds"):
        with pytest.raises(ValueError):
            OidcSubjectRegistry.from_document(
                _document(_row(**{field: value})), expected_issuer=_ISSUER
            )


@pytest.mark.parametrize(
    "document",
    [
        {"version": "oidc-subject-registry.v3", "subjects": [_row()]},
        {"version": "oidc-subject-registry.v1.1", "subjects": [_row()]},
        {"version": None, "subjects": [_row()]},
        {"version": "oidc-subject-registry.v2", "subjects": []},
        {"version": "oidc-subject-registry.v2"},
        {"version": "oidc-subject-registry.v2", "subjects": [_row(unexpected=True)]},
        {"version": "oidc-subject-registry.v2", "subjects": [dict(_row()), dict(_row())]},
        {
            "version": "oidc-subject-registry.v2",
            "subjects": [
                _row(principalId="shared"),
                _row(subject="subject-2", principalId="shared"),
            ],
        },
        {"version": "oidc-subject-registry.v2", "subjects": [_row(role="UNKNOWN")]},
        {"version": "oidc-subject-registry.v2", "subjects": [_row(status="PAUSED")]},
        {"version": "oidc-subject-registry.v2", "subjects": [_row(issuer="https://other.test")]},
    ],
)
def test_v2_rejects_unknown_version_rows_and_never_falls_back(
    document: dict[str, Any],
) -> None:
    # v2 파싱 실패는 v1 재시도로 이어지지 않는다 — 세 번째 케이스처럼 version
    # 누락/v1 전용 문법이어도 null 전체 허용으로 승격되지 않고 즉시 거부된다.
    with pytest.raises(ValueError):
        OidcSubjectRegistry.from_document(document, expected_issuer=_ISSUER)


# ── 3. 한계값 ─────────────────────────────────────────────────────────


def test_v2_bounds_hold_at_existing_limits() -> None:
    rows = [_row(subject=f"subject-{index}", principalId=f"user-{index}") for index in range(512)]
    registry = OidcSubjectRegistry.from_document(
        {"version": "oidc-subject-registry.v2", "subjects": rows}, expected_issuer=_ISSUER
    )
    assert registry.resolve(_ISSUER, "subject-1") is not None

    with pytest.raises(ValueError):
        OidcSubjectRegistry.from_document(
            {
                "version": "oidc-subject-registry.v2",
                "subjects": rows + [_row(subject="subject-512", principalId="user-512")],
            },
            expected_issuer=_ISSUER,
        )
    with pytest.raises(ValueError):
        OidcSubjectRegistry.from_document(
            _document(_row(allowedSiteIds=[f"site-{index}" for index in range(513)])),
            expected_issuer=_ISSUER,
        )
    OidcSubjectRegistry.from_document(
        _document(_row(allowedSiteIds=[f"site-{index}" for index in range(512)])),
        expected_issuer=_ISSUER,
    )
    OidcSubjectRegistry.from_document(
        _document(_row(subject="s" * 2048, principalId="p" * 2048)), expected_issuer=_ISSUER
    )
    with pytest.raises(ValueError):
        OidcSubjectRegistry.from_document(
            _document(_row(subject="s" * 2049)), expected_issuer=_ISSUER
        )


# ── 4. 보호 파일 경계 ─────────────────────────────────────────────────


def _write_registry(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "subjects-v2.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_v2_loader_keeps_private_file_requirements(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, _document(_row(allowedSiteIds=None, allowedWorkAreaIds=None)))
    registry = load_oidc_subject_registry(path, expected_issuer=_ISSUER)
    assert registry.resolve(_ISSUER, "provider-subject-1") is not None

    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_oidc_subject_registry(path, expected_issuer=_ISSUER)
    path.chmod(0o600)

    link = tmp_path / "subjects-v2-link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="unsafe"):
        load_oidc_subject_registry(link, expected_issuer=_ISSUER)

    hardlink = tmp_path / "subjects-v2-hardlink.json"
    hardlink.hardlink_to(path)
    with pytest.raises(ValueError):
        load_oidc_subject_registry(hardlink, expected_issuer=_ISSUER)
    hardlink.unlink()

    path.write_text(json.dumps({"version": "oidc-subject-registry.v2", "subjects": [float("nan")]}))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="JSON"):
        load_oidc_subject_registry(path, expected_issuer=_ISSUER)

    oversized = tmp_path / "subjects-v2-oversized.json"
    oversized.write_text(" " * (64 * 1024 + 1), encoding="utf-8")
    oversized.chmod(0o600)
    with pytest.raises(ValueError):
        load_oidc_subject_registry(oversized, expected_issuer=_ISSUER)


# ── 5. opaque 토큰 설정은 capability 발급 표면이 아니다 ────────────────


@pytest.mark.parametrize("reserved", ["registryScoped", "capabilities"])
def test_token_config_rejects_registry_reserved_fields(reserved: str) -> None:
    entry = {
        "tokenSha256": "a" * 64,
        "principalId": "opaque-user",
        "kind": "OPERATOR",
        "role": "ADMIN",
        "deviceId": None,
        reserved: True,
    }
    with pytest.raises(RuntimeError, match=reserved):
        _parse_principal_tokens(json.dumps([entry]))


# ── 6. schema corpus — 문법은 schema, semantics 는 parser ─────────────


def _schema_validator() -> Draft202012Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize(
    "document",
    [
        _document(_row(allowedSiteIds=None, allowedWorkAreaIds=None)),
        _document(_row(capabilities=["SITE_BOOTSTRAP"])),
        _document(_row(allowedSiteIds=[], allowedWorkAreaIds=[])),
        _document(
            _row(allowedSiteIds=["site-a", "site-b"], allowedWorkAreaIds=None),
            _row(subject="s2", principalId="p2"),
        ),
    ],
)
def test_schema_accepts_valid_v2_documents_and_parser_agrees(
    document: dict[str, Any],
) -> None:
    assert _schema_validator().is_valid(document)
    OidcSubjectRegistry.from_document(document, expected_issuer=_ISSUER)


@pytest.mark.parametrize(
    "document",
    [
        {"version": "oidc-subject-registry.v1", "subjects": [_row()]},
        {"version": "oidc-subject-registry.v2", "subjects": []},
        {"version": "oidc-subject-registry.v2", "subjects": [dict(_row(), extra=True)]},
        _document(dict(_row(), **{"capabilities": None})),
        _document(_row(capabilities=["UNKNOWN"])),
        _document(_row(capabilities=["SITE_BOOTSTRAP", "SITE_BOOTSTRAP"])),
        _document(_row(allowedSiteIds="site-1")),
        _document(_row(allowedSiteIds=[1])),
        _document(_row(allowedSiteIds=["a/b"])),
        _document(_row(role="UNKNOWN")),
        _document(_row(status="PAUSED")),
        _document(_row(principalId="../escape")),
        {"version": "oidc-subject-registry.v2", "subjects": [{"issuer": _ISSUER}]},
    ],
)
def test_schema_rejects_invalid_v2_shape_and_parser_agrees(document: dict[str, Any]) -> None:
    assert not _schema_validator().is_valid(document)
    with pytest.raises(ValueError):
        OidcSubjectRegistry.from_document(document, expected_issuer=_ISSUER)


def test_schema_cannot_replace_parser_semantics() -> None:
    """schema 가 표현하지 못하는 semantic 거부 — 통과가 로드 성공이 아니다."""
    duplicates_in_scope = _document(_row(allowedSiteIds=["site-1", "site-1"]))
    duplicate_rows = {
        "version": "oidc-subject-registry.v2",
        "subjects": [_row(), dict(_row())],
    }
    wrong_issuer = _document(_row(issuer="https://other.test"))

    validator = _schema_validator()
    for document in (duplicates_in_scope, duplicate_rows, wrong_issuer):
        assert validator.is_valid(document)
        with pytest.raises(ValueError):
            OidcSubjectRegistry.from_document(document, expected_issuer=_ISSUER)
