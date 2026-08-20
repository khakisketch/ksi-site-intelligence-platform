"""프로덕션 조립 지점(ksi_core.production)의 계약 테스트.

``tests/contract/test_dev_assembly.py`` 가 저장소의 유일한 실행 가능 dev 조립을
검증하는 것과 대칭으로, 이 파일은 유일한 실행 가능 **운영** 조립을 검증한다.
핵심 우려는 세 가지다 — ①dev 토큰이 운영 빌드에 섞여 들어오지 않는다,
②필수 환경변수 부재가 조용히 기본값으로 넘어가지 않고 fail-closed 로 즉시
거부된다, ③``assemble_app`` 한 곳을 dev·production 이 공유하므로 그 공유
지점이 ``create_app`` 의 모든 store 파라미터를 실제로 채운다.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import ksi_core.app_assembly as app_assembly_module
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.app_assembly import assemble_app
from ksi_core.durable_journal import DurableJournal
from ksi_core.edge_sync import EdgeSyncStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_SOURCE = (
    _REPO_ROOT / "services" / "core" / "src" / "ksi_core" / "production.py"
).read_text(encoding="utf-8")

_DEV_TOKEN_LITERALS = [
    "dev-admin-token",
    "dev-field-operator-token",
    "dev-viewer-token",
    "dev-edge-device-token",
    "dev-processing-worker-token",
]

_ALL_REQUIRED_ENV = (
    "KSI_CORE_DATA_DIR",
    "KSI_CORE_SIGNING_KEYS_DIR",
    "KSI_CORE_S3_ENDPOINT",
    "KSI_CORE_S3_BUCKET",
    "KSI_CORE_PRINCIPAL_TOKENS_JSON",
    "KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE",
)


# ── 1. dev 토큰·dev 모듈 의존 부재 (소스 텍스트 검사) ───────────────────────


def test_production_source_contains_no_dev_token_literals() -> None:
    """production.py 소스에 dev 고정 토큰 문자열이 단 하나도 없다."""
    for literal in _DEV_TOKEN_LITERALS:
        assert literal not in _PRODUCTION_SOURCE, (
            f"production.py 에 dev 토큰 리터럴이 있다: {literal!r} — "
            "운영 빌드가 dev 자격증명을 끌고 들어올 수 있다"
        )


def test_production_does_not_import_run_core_dev() -> None:
    """production.py 는 run_core_dev 를 import 하지 않는다 — dev 모듈에 대한 의존 없음.

    모듈 docstring 은 산문으로 ``scripts/run_core_dev.py`` 를 **언급**한다(dev 조립과의
    대비 설명) — 그건 의존이 아니다. 여기서 거부하는 것은 실제 import 문뿐이다.
    """
    assert "import run_core_dev" not in _PRODUCTION_SOURCE
    assert "from run_core_dev" not in _PRODUCTION_SOURCE


# ── 2. 필수 환경변수 부재 → RuntimeError(fail-closed) ───────────────────────


def _write_signing_keys(keys_dir: Path) -> None:
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_id = "core-prod-test-key"
    key = Ed25519PrivateKey.generate()
    (keys_dir / f"{key_id}.private.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (keys_dir / f"{key_id}.private.pem").chmod(0o600)
    (keys_dir / f"{key_id}.public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    (keys_dir / "keys.json").write_text(
        json.dumps({"active": key_id, "keys": [{"keyId": key_id, "status": "ACTIVE"}]}),
        encoding="utf-8",
    )


def _valid_env(tmp_path: Path) -> dict[str, str]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    signing_dir = tmp_path / "signing"
    _write_signing_keys(signing_dir)
    attestation_manifest = tmp_path / "device-attestation-keys.json"
    attestation_manifest.write_text(json.dumps({"keys": []}), encoding="utf-8")

    tokens = [
        {
            "tokenSha256": hashlib.sha256(b"prod-admin-token").hexdigest(),
            "principalId": "prod-admin",
            "kind": "OPERATOR",
            "role": "ADMIN",
            "deviceId": None,
        }
    ]
    return {
        "KSI_CORE_DATA_DIR": str(data_dir),
        "KSI_CORE_SIGNING_KEYS_DIR": str(signing_dir),
        "KSI_CORE_S3_ENDPOINT": "http://127.0.0.1:9000",
        "KSI_CORE_S3_BUCKET": "prod-evidence",
        "KSI_CORE_PRINCIPAL_TOKENS_JSON": json.dumps(tokens),
        "KSI_CORE_DEVICE_ATTESTATION_KEYS_FILE": str(attestation_manifest),
    }


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("missing", _ALL_REQUIRED_ENV)
def test_missing_required_env_var_raises_runtime_error(
    missing: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """다섯 필수 환경변수 중 하나라도 빠지면 RuntimeError — 조용히 기본값으로 넘어가지 않는다."""
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    del env[missing]
    _apply_env(monkeypatch, env)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(RuntimeError):
        build_production_app()


def test_missing_env_var_fails_before_heavy_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 엔드포인트가 없으면 boto3 client 조립(무거운 부수효과) 전에 이미 죽는다.

    가장 뒤에 검증되는 값 중 하나(S3_BUCKET)를 지워 이 순서를 확인한다 — 이보다
    앞서 조립되는 무거운 자원(journal 파일 등)이 생기기 전에 실패해야 한다.
    """
    from ksi_core.production import build_production_app

    env = _valid_env(tmp_path)
    del env["KSI_CORE_S3_BUCKET"]
    _apply_env(monkeypatch, env)
    monkeypatch.delenv("KSI_CORE_S3_BUCKET", raising=False)

    with pytest.raises(RuntimeError, match="KSI_CORE_S3_BUCKET"):
        build_production_app()
    # 검증 실패 시점에는 아직 어떤 journal 파일도 만들어지지 않았어야 한다 —
    # 무거운 조립(2단계)에 진입하기 전에 1단계 검증이 전부 끝난다는 증거.
    data_dir = Path(env["KSI_CORE_DATA_DIR"])
    assert list(data_dir.iterdir()) == []


def test_malformed_principal_tokens_json_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = "not-json"
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError, match="KSI_CORE_PRINCIPAL_TOKENS_JSON"):
        build_production_app()


def test_unknown_principal_kind_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(b"x").hexdigest(),
                "principalId": "p1",
                "kind": "NOT_A_KIND",
                "role": None,
                "deviceId": None,
            }
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError):
        build_production_app()


def test_plaintext_token_sha256_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tokenSha256`` 에 원문 토큰(digest 아님)이 실리면 1단계 검증에서 즉시 거부한다.

    ``AuthRegistry`` 도 같은 값을 거부하지만(``_TOKEN_SHA256_RE``) 그건 2단계(무거운
    조립 이후)다 — 이 테스트는 형식 검증이 그보다 앞서 fail-closed 로 걸린다는 것과,
    예외 메시지가 어느 env 가 문제인지 이름을 남긴다는 것(독립 재검토 지적 A2)을 함께
    고정한다.
    """
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": "dev-admin-token",
                "principalId": "p1",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
            }
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError, match="KSI_CORE_PRINCIPAL_TOKENS_JSON"):
        build_production_app()


def test_negative_journal_segment_bytes_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``KSI_CORE_JOURNAL_SEGMENT_BYTES=-1`` 도 다른 형식 오류처럼 RuntimeError 다.

    ``cli_optional_positive`` (dev CLI 와 공유하는 라이브러리 계약)는 음수를
    ``ValueError`` 로 거부한다 — 이 함수는 환경변수 검증 경계이므로 모듈 docstring
    이 약속한 "형식이 틀리면 RuntimeError"를 이 입력에 대해서도 지켜야 한다(독립
    재검토 지적 A3, 이전 버전은 여기서 ValueError 가 새어 나갔다).
    """
    env = _valid_env(tmp_path)
    env["KSI_CORE_JOURNAL_SEGMENT_BYTES"] = "-1"
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError):
        build_production_app()


def test_unknown_token_status_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(b"x").hexdigest(),
                "principalId": "p1",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
                "status": "SUSPENDED",
            }
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError, match="status"):
        build_production_app()


def test_naive_not_after_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``notAfter`` 에 tz 없는 ISO 문자열이 오면 거부한다 — signing_keys.py 의
    같은 검증(naive datetime 은 만료 비교에서 fail-closed 를 깬다)과 동일 이유."""
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(b"x").hexdigest(),
                "principalId": "p1",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
                "notAfter": "2026-01-01T00:00:00",
            }
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    with pytest.raises(RuntimeError, match="notAfter"):
        build_production_app()


def test_rotation_overlap_lets_old_and_new_token_both_authenticate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[핵심] 회전 절차의 핵심 성질 — 같은 ``principalId`` 로 발급된 새 토큰과
    유예기간이 아직 안 지난 이전 토큰이 **동시에** 인증된다. 문서
    (``docs/security/AUTH_TOKEN_ROTATION.md``)가 약속하는 겹침 구간이 실제
    ``build_production_app`` 조립에서도 성립하는지 HTTP 경계로 확인한다."""
    old_token = "old-rotating-token"  # noqa: S105 -- 테스트 고정값
    new_token = "new-rotating-token"  # noqa: S105 -- 테스트 고정값
    env = _valid_env(tmp_path)
    env["KSI_CORE_PRINCIPAL_TOKENS_JSON"] = json.dumps(
        [
            {
                "tokenSha256": hashlib.sha256(new_token.encode()).hexdigest(),
                "principalId": "rotating-admin",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
            },
            {
                "tokenSha256": hashlib.sha256(old_token.encode()).hexdigest(),
                "principalId": "rotating-admin",
                "kind": "OPERATOR",
                "role": "ADMIN",
                "deviceId": None,
                "notAfter": "2099-01-01T00:00:00Z",
            },
        ]
    )
    _apply_env(monkeypatch, env)

    from ksi_core.production import build_production_app

    client = TestClient(build_production_app())
    old_response = client.get("/v1/auth/whoami", headers={"Authorization": f"Bearer {old_token}"})
    new_response = client.get("/v1/auth/whoami", headers={"Authorization": f"Bearer {new_token}"})

    assert old_response.status_code == 200
    assert new_response.status_code == 200
    assert old_response.json()["principalId"] == "rotating-admin"
    assert new_response.json()["principalId"] == "rotating-admin"


# ── 3. 정상 env → FastAPI 인스턴스 ─────────────────────────────────────────


def test_valid_env_builds_fastapi_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 환경변수 세트로 ``build_production_app`` 이 FastAPI 인스턴스를 반환한다.

    S3 엔드포인트 값 자체는 검증만 되고 실제 연결은 만들어지지 않는다 —
    boto3 client 생성은 네트워크 왕복 없이 성공한다(어댑터가 지연 발급하는
    presigned URL 시점에만 실제 통신이 일어난다).
    """
    _apply_env(monkeypatch, _valid_env(tmp_path))

    from ksi_core.production import build_production_app

    app = build_production_app()
    assert isinstance(app, FastAPI)


def test_expose_docs_defaults_closed_and_opens_when_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KSI_CORE_EXPOSE_DOCS 미설정이면 /docs 가 404, "true" 면 열린다."""
    from ksi_core.production import build_production_app

    # 서로 다른 data-dir — 같은 디렉터리로 두 번 조립하면 첫 조립이 연 journal 의
    # flock 을 아직 쥐고 있어(테스트가 close 하지 않는다) 두 번째 조립이
    # JournalRecoveryError("다른 프로세스가 소유 중")로 실패한다(단일 writer 불변식).
    closed_env = _valid_env(tmp_path / "closed")
    _apply_env(monkeypatch, closed_env)
    monkeypatch.delenv("KSI_CORE_EXPOSE_DOCS", raising=False)
    closed_app = build_production_app()
    closed_client = TestClient(closed_app)
    assert closed_client.get("/docs").status_code == 404

    open_env = _valid_env(tmp_path / "open")
    _apply_env(monkeypatch, open_env)
    monkeypatch.setenv("KSI_CORE_EXPOSE_DOCS", "true")
    open_app = build_production_app()
    open_client = TestClient(open_app)
    assert open_client.get("/docs").status_code == 200


# ── 4. assemble_app 이 create_app 의 모든 *_store 파라미터를 채운다 ─────────
#
# dev(run_core_dev.py)와 production 양쪽이 assemble_app 하나를 거치므로, 이
# 인트로스펙션 대조는 여기 한 번만 있으면 충분하다(test_dev_assembly.py 의
# test_max_assembly_passes_every_store_parameter 와 동형 — 대상만 assemble_app).


def test_assemble_app_wires_every_create_app_store_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``assemble_app`` 이 ``create_app`` 의 모든 ``*_store`` 인자를 실제로 채우는지,
    이름 집합을 서로 대조해 확인한다.

    이전 버전은 ``store_params``(``create_app`` 시그니처에서 뽑은 집합)를 어디와도
    대조하지 않고 ``assert store_params``/``assert paths`` 두 비어있음 검사만 했다 —
    ``assemble_app`` 이 ``equipment_support_store`` 등을 통째로 안 넘기게 되어도
    그 버전은 green 이었다(독립 재검토 지적 A1). ``ksi_core.app_assembly.create_app`` 을
    가로채 실제로 넘어온 kwargs 이름을 캡처해 ``store_params`` 와 진짜 차집합을 낸다.
    """
    store_params = {
        name for name in inspect.signature(create_app).parameters if name.endswith("_store")
    }

    captured_kwargs: dict[str, Any] = {}
    original_create_app = create_app

    def _capturing_create_app(**kwargs: Any) -> FastAPI:
        captured_kwargs.update(kwargs)
        return original_create_app(**kwargs)

    monkeypatch.setattr(app_assembly_module, "create_app", _capturing_create_app)

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / name)
        opened.append(journal)
        return journal

    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role

    auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"x").hexdigest(),
                principal=Principal(
                    principal_id="op-1", kind=PrincipalKind.OPERATOR, role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )

    class _NullEvidenceStorage:
        def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
            raise NotImplementedError

        def presigned_get(self, object_key: str, *, ttl: Any) -> str:
            raise NotImplementedError

        def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
            del object_key, data, content_type

        def get_bytes(self, object_key: str) -> bytes:
            raise NotImplementedError

        def delete(self, object_key: str) -> None:
            raise NotImplementedError

    app = assemble_app(
        tmp_path,
        journal=_journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=auth_registry,
        evidence_storage=_NullEvidenceStorage(),
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="assemble-app-test-key",
    )
    try:
        paths = {p for p in app.openapi()["paths"] if p.startswith("/v1/")}
    finally:
        for journal in opened:
            journal.close()

    assert store_params, "create_app 시그니처에서 *_store 파라미터를 하나도 못 찾았다(테스트 결함)"
    assert paths, "assemble_app 이 어떤 /v1 경로도 장착하지 않았다"

    # 핵심 대조 — assemble_app 이 create_app 에 실제로 넘긴 kwargs 이름과 시그니처의
    # *_store 파라미터 이름 집합의 차집합. 여기가 비지 않으면 새 store 파라미터를
    # create_app 에 추가하고 assemble_app 을 안 고쳐도 이 테스트가 조용히 통과하던
    # 사각지대가 다시 열린 것이다.
    missing = store_params - set(captured_kwargs)
    assert not missing, (
        f"assemble_app 이 create_app 의 store 파라미터를 넘기지 않는다: {sorted(missing)} "
        "— assemble_app 이 evidence_storage 를 받았으므로 조건부 store 도 전부 채워져야 한다"
    )


# ── 5. /ready — 봉인 원장이 있으면 503 ──────────────────────────────────────


def test_ready_is_200_when_nothing_sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _apply_env(monkeypatch, _valid_env(tmp_path))
    from ksi_core.production import build_production_app

    app = build_production_app()
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


def test_ready_is_503_when_a_journal_is_sealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """opened 원장 하나를 append 실패로 봉인시키면 /ready 가 503 이다.

    봉인 유발 관용구는 test_durable_journal.py::test_write_failure_seals_and_rejects_
    subsequent_appends 를 그대로 재사용한다(``_WRITE`` 모듈 참조를 예외로 대체).
    production 이 여는 원장도 ``assemble_app`` 이 연 것과 동일 클래스(``DurableJournal``)
    이므로, ``assemble_app`` 을 직접 불러 조립한 앱으로 확인하면 production 경로의
    ``/ready`` 배선(같은 함수)을 그대로 검증한 것과 같다.
    """
    from ksi_core import durable_journal as durable_journal_module

    def broken_write(_fd: int, _data: Any) -> int:
        raise OSError("disk full (주입 실패)")

    from ksi_core.app_assembly import assemble_app as _assemble_app
    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / "ready-seal" / name)
        opened.append(journal)
        return journal

    auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"y").hexdigest(),
                principal=Principal(
                    principal_id="op-2", kind=PrincipalKind.OPERATOR, role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )
    seal_app = _assemble_app(
        tmp_path / "ready-seal",
        journal=_journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=auth_registry,
        evidence_storage=None,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="ready-seal-test-key",
    )
    try:
        client = TestClient(seal_app)
        assert client.get("/ready").status_code == 200

        monkeypatch.setattr(durable_journal_module, "_WRITE", broken_write)
        with pytest.raises(Exception):  # noqa: B017, PT011 -- JournalSealedError, 원인만 필요
            opened[0].append({"n": 0})
        monkeypatch.undo()

        assert opened[0].sealed_reason is not None
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["ready"] is False
    finally:
        for journal in opened:
            journal.close()


def test_ready_is_503_when_edge_sync_store_is_sealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``EdgeSyncStore`` 봉인도 ``/ready`` 에 반영된다(P0-1 회귀 고정).

    수정 전에는 ``EdgeSyncStore`` 가 ``sealed_reason`` property 를 노출하지
    않아 ``app_assembly.ready()`` 의 ``getattr(j, "sealed_reason", None)`` 이
    기본값 ``None`` 에 걸렸다 — 이 store 가 봉인돼도 ``/ready`` 는 계속 200 을
    냈다(edge-sync 수신 전부가 503 인데 오케스트레이터는 정상으로 오판).
    """
    from ksi_core.app_assembly import assemble_app as _assemble_app
    from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role

    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(tmp_path / "ready-seal-edge" / name)
        opened.append(journal)
        return journal

    auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"z").hexdigest(),
                principal=Principal(
                    principal_id="op-3", kind=PrincipalKind.OPERATOR, role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )
    seal_app = _assemble_app(
        tmp_path / "ready-seal-edge",
        journal=_journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=auth_registry,
        evidence_storage=None,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="ready-seal-edge-test-key",
    )
    try:
        client = TestClient(seal_app)
        assert client.get("/ready").status_code == 200

        edge_sync_store = next(o for o in opened if isinstance(o, EdgeSyncStore))
        # close() 는 EdgeSyncStore.close() 문서화대로 sealed_reason 을 "closed"
        # 로 남긴다 — DurableJournal 과 동일한 봉인 의미론(durable_journal.py:396
        # 대칭)이므로, append 실패를 재현하지 않고도 봉인 상태를 만들 수 있다.
        edge_sync_store.close()

        assert edge_sync_store.sealed_reason is not None
        response = client.get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["sealedCount"] >= 1
    finally:
        # close() 는 두 원장 타입 모두 멱등이다 — 이미 닫힌 edge_sync_store 도
        # 안전하게 다시 닫을 수 있다(위 close() 문서 참조).
        for journal in opened:
            journal.close()
