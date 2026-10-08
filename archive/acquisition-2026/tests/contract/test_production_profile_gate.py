"""INV-040 강제 게이트 — 운영 조립의 import closure 에 mock/dev 모듈이 없다.

INV-040 은 "Production 에서 mock/placeholder/static always-go 금지"를 요구하고
강제 수단으로 *코드리뷰 게이트 + production profile 테스트* 를 병기한다. 앞의 것은
사람이고, 이 파일이 뒤의 것이다.

**이 저장소에 "production profile" 이라는 설정값은 없다.** ``KSI_ENV``·``KSI_PROFILE``
류 환경변수가 아예 없고(grep 0건), 프로파일은 오직 **어느 진입점을 실행하는가**로만
정의된다 — Core 는 ``Dockerfile`` CMD → :func:`ksi_core.production.build_production_app`.
(P3 Task 3 에서 managed 처리 워커 진입점(``Dockerfile.worker`` CMD →
``ksi_processing_controller.runner:main``)은 ``archive/acquisition-2026/`` 으로
분리됐다 — 분리 자체의 존재 고정은
``tests/contract/test_acquisition_archive_boundary.py`` 가 맡고, 이 파일은 Core
진입점과 surviving platform lane 전체의 closure 를 검사한다.)
그래서 이 게이트도 설정을 읽지 않고 **Core 진입점과 lane 모듈들을 실제로 실행해
sys.modules 를 본다**.

``tests/contract/test_production_assembly.py`` 가 이미 dev 토큰 리터럴과
``run_core_dev`` import 를 막지만 **``production.py`` 파일 한 개의 텍스트만** 읽는다 —
``app_assembly.py`` 를 포함한 나머지 조립 경로 전체가 사각지대였다. 이 파일은 그
검사를 closure 전체로 넓힌다.

이 게이트는 신규 요구가 아니라 **현재 성질의 회귀 금지**다(2026-08-18 실측: 두
진입점 모두 mock 계열 미로드). ``tests/contract/test_anti_circularity_gate.py`` 가
자기 목적을 그렇게 적은 것과 같은 구조이고, 그 파일의 두 관례를 그대로 따른다 —
①별도 파일로 격리하고 fixture 를 공유 conftest 로 빼지 않는다(중복이 여기서는 비용이
아니라 격리다. 다른 테스트의 fixture 변경이 이 게이트의 판정을 바꾸면 안 된다),
②"공허 방지" 단언을 함께 건다(검사 대상이 실제로 존재했음을 증명하지 못하면 초록불이
거짓말이 된다).

**subprocess 를 쓰는 이유**: pytest 는 한 프로세스에서 전 테스트를 수집·실행하므로
``sys.modules`` 가 다른 테스트 파일의 import 로 오염된다. in-process 로 짜면 오늘은
우연히 통과하고(저장소 어느 테스트도 ``unittest.mock`` 을 import 하지 않는다) 누가
mock 을 쓰는 테스트를 하나 추가하는 순간 무관한 이유로 깨지거나 판정이 실행 순서에
종속된다. 그건 게이트가 아니다.

**이 게이트가 못 보는 것**: 모듈 단위만 본다. ``httpx.MockTransport`` 처럼 정상
런타임 라이브러리 **안의 클래스**로 만드는 가짜는 모듈 이름으로 잡히지 않는다.
그 축은 INV-040 이 병기한 코드리뷰 게이트 몫으로 남는다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 운영 closure 에 있으면 안 되는 모듈. **정확일치 또는 점(.) 프리픽스 일치만** 쓴다 —
# 부분문자열 매칭은 정상 런타임 모듈을 오탐한다(2026-08-18 실측: anyio._core._testing,
# anyio.abc._testing, pydantic._internal._mock_val_ser).
_FORBIDDEN_MODULE_PREFIXES = (
    "unittest.mock",
    "pytest",
    "_pytest",
    "moto",
    "responses",
    "respx",
    "faker",
    "run_core_dev",
    "conftest",
    # packages/test-vectors 아래라 경로 검사(references/scripts/tests)에도 안 걸린다 —
    # 이름으로 막지 않으면 어느 검사에도 안 잡힌다.
    "ksi_test_vectors",
    # Offline replay/model-evaluation plane. EventBundle에 productionEvidence=false와
    # vertical-slice-demo를 싣고 Core도 typed 거부한다. 운영 closure에 들어오면
    # native Edge runtime 경계와 INV-040을 동시에 깨므로 계속 금지한다.
    "ksi_perception.pipeline",
)

_DEV_TOKEN_LITERALS = (
    "dev-admin-token",
    "dev-field-operator-token",
    "dev-viewer-token",
    "dev-edge-device-token",
    "dev-gateway-device-token",
    "dev-processing-worker-token",
)

# closure 덤프를 만드는 자식 프로세스 스크립트. 결과는 stdout 이 아니라 파일로
# 넘긴다 — 로깅 핸들러가 stderr 로 가더라도 파일 경유가 더 견고하다.
_DUMP_TEMPLATE = """\
import json, sys
{body}
modules = {{
    name: getattr(mod, "__file__", None)
    for name, mod in sorted(sys.modules.items())
    if mod is not None
}}
with open({out!r}, "w", encoding="utf-8") as handle:
    json.dump(modules, handle)
"""

_CORE_BODY = """\
from ksi_core.production import build_production_app
build_production_app()
"""

# 처리 워커 진입점 자체는 P3 Task 3 에서 archive 로 분리됐다(runner 모듈이
# archive 로 이동해 이 파일에서 import 할 수 없다) — 분리 자체의 존재 고정은
# ``tests/contract/test_acquisition_archive_boundary.py`` 가 맡고, surviving
# platform lane 의 closure 검사는 아래 ``_LANE_BODY`` 가 이어받는다.


def _lane_module_lists() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """경계 파일의 surviving 모듈 목록을 파일 위치로 읽는다 — sys.path 변경 없이.

    목록 SSOT 는 ``tests/contract/test_acquisition_archive_boundary.py`` 이다.
    그 파일을 직접 실행해 ``(_SURVIVING_ENTRYPOINT_MODULES,
    _SURVIVING_LANE_MODULES)`` 를 가져오므로 두 파일의 목록이 드리프트할 수
    없다(모듈 수준 코드는 상수 정의뿐이라 실행해도 부작용이 없다).
    """
    path = _REPO_ROOT / "tests" / "contract" / "test_acquisition_archive_boundary.py"
    spec = importlib.util.spec_from_file_location("test_acquisition_archive_boundary", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    entrypoints: tuple[str, ...] = module._SURVIVING_ENTRYPOINT_MODULES
    lanes: tuple[str, ...] = module._SURVIVING_LANE_MODULES
    return entrypoints, lanes


_LANE_ENTRYPOINT_MODULES, _LANE_MODULES = _lane_module_lists()
_LANE_BODY = "".join(f"import {name}\n" for name in (*_LANE_ENTRYPOINT_MODULES, *_LANE_MODULES))

# 레인 closure 공허 방지 앵커 — surviving lane 에서만 나오는 모듈이라야 의미가 있다.
_LANE_ANCHOR_MODULE = "ksi_processing_controller.external_analysis_runner"


def forbidden_modules(loaded: Iterable[str]) -> tuple[str, ...]:
    """금지 모듈만 골라 정렬해 반환한다 — 정확일치 또는 점 프리픽스 일치.

    판정을 순수 함수로 빼는 이유는 합성 입력으로 **탐지기 자체가 no-op 이 아님**을
    시험하기 위해서다(``tests/contract/test_repo_hygiene_gate.py`` 의 규율:
    "스크립트가 0을 반환한다"가 아니라 "위반을 주입하면 실제로 실패한다"를 본다).
    """
    hits = {
        name
        for name in loaded
        for prefix in _FORBIDDEN_MODULE_PREFIXES
        if name == prefix or name.startswith(prefix + ".")
    }
    return tuple(sorted(hits))


def _write_signing_keys(keys_dir: Path) -> None:
    """test_production_assembly.py 에서 의도적으로 복제 — 위 docstring 의 격리 이유 참조."""
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_id = "core-prod-gate-key"
    key = Ed25519PrivateKey.generate()
    private_path = keys_dir / f"{key_id}.private.pem"
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
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
    """운영 조립이 요구하는 필수 환경변수.

    ``production.py`` 가 필수 환경변수를 늘리면 이 함수와
    ``test_production_assembly.py:_valid_env`` **둘 다** 고쳐야 한다 — 복제는 격리
    목적이라 유지하지만, 고치는 사람이 두 곳을 봐야 한다는 사실을 여기 남긴다.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    signing_dir = tmp_path / "signing"
    _write_signing_keys(signing_dir)
    attestation_manifest = tmp_path / "device-attestation-keys.json"
    attestation_manifest.write_text(json.dumps({"keys": []}), encoding="utf-8")
    tokens = [
        {
            "tokenSha256": hashlib.sha256(b"prod-gate-token").hexdigest(),
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


def _dump_closure(body: str, tmp_path: Path, env: dict[str, str] | None = None) -> dict[str, str]:
    """자식 프로세스에서 ``body`` 를 실행하고 그 시점 ``sys.modules`` 를 돌려준다."""
    out_path = tmp_path / "closure.json"
    script = _DUMP_TEMPLATE.format(body=body, out=str(out_path))
    child_env = dict(env or {})
    child_env.setdefault("PATH", "/usr/bin:/bin")
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
        env=child_env,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        pytest.fail(
            f"운영 진입점 실행이 실패했다 (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    loaded: dict[str, str] = json.loads(out_path.read_text(encoding="utf-8"))
    return loaded


# 공허 방지 앵커 — Core closure 에서만 나오는 모듈이라야 의미가 있다.
_ANCHOR_MODULE = "ksi_core.app_assembly"


def test_forbidden_module_detector_is_not_a_no_op() -> None:
    """탐지기가 실제로 잡고, 정상 모듈은 오탐하지 않는다.

    두 번째 단언이 핵심이다 — 부분문자열 매칭으로 회귀하면 여기서 걸린다.
    """
    assert forbidden_modules(["ksi_core.app", "unittest.mock"]) == ("unittest.mock",)
    assert forbidden_modules(["pytest", "ksi_core.app"]) == ("pytest",)
    assert forbidden_modules(["ksi_perception.pipeline"]) == ("ksi_perception.pipeline",)
    assert forbidden_modules(["anyio._core._testing", "pydantic._internal._mock_val_ser"]) == ()
    assert forbidden_modules(["ksi_perception.detector"]) == ()


def test_core_production_closure_loads_no_mock_or_dev_module(tmp_path: Path) -> None:
    """Core 운영 조립을 **실제로 호출한** 뒤의 import closure 가 깨끗하다."""
    loaded = _dump_closure(_CORE_BODY, tmp_path, env=_valid_env(tmp_path))

    # 공허 방지 — 조립이 실제로 끝까지 갔는지부터 확인한다. evidence_s3/boto3 는
    # production.py 에서 지연 import 되므로, 이 둘이 있어야 "모듈 import 만 하고
    # 조립은 안 했다"가 아님이 증명된다.
    assert "ksi_core.app_assembly" in loaded
    assert "ksi_core.evidence_s3" in loaded
    assert "boto3" in loaded

    hits = forbidden_modules(loaded)
    assert hits == (), f"운영 closure 에 금지 모듈이 실렸다: {hits}"


def test_lane_closure_loads_no_mock_or_dev_module(tmp_path: Path) -> None:
    """surviving platform lane 진입점+공유 모듈의 import closure 도 같은 기준으로 깨끗하다.

    분리 전 ``test_worker_closure_loads_no_mock_or_dev_module`` 이 보던 자리를
    잇는다 — managed 데몬 대신 7개 platform 진입점과 공유 lane 모듈 전체를
    실제로 import 한 뒤의 closure 를 본다.
    """
    loaded = _dump_closure(_LANE_BODY, tmp_path)

    # 공허 방지 — 레인 모듈이 실제로 로드됐는지부터 확인한다.
    assert _LANE_ANCHOR_MODULE in loaded

    hits = forbidden_modules(loaded)
    assert hits == (), f"레인 closure 에 금지 모듈이 실렸다: {hits}"


@pytest.mark.parametrize("closure", ["core", "lane"])
def test_no_production_closure_module_lives_under_references_or_scripts_or_tests(
    closure: str, tmp_path: Path
) -> None:
    """운영 closure 의 어떤 모듈도 references/·scripts/·tests/ 아래에서 오지 않는다.

    CLAUDE.md 의 "Never import runtime code directly from ``references/``" 를 기계로
    검사하는 첫 지점이다. Core 진입점과 platform lane closure **둘 다** 검사한다 —
    Core 만 보면 lane 모듈 상당수가 영원히 사각지대로 남는다. 분리된 managed
    데몬 closure 의 존재 자체는
    ``tests/contract/test_acquisition_archive_boundary.py`` 가 고정한다.
    """
    if closure == "core":
        loaded = _dump_closure(_CORE_BODY, tmp_path, env=_valid_env(tmp_path))
        anchor = _ANCHOR_MODULE
    else:
        loaded = _dump_closure(_LANE_BODY, tmp_path)
        anchor = _LANE_ANCHOR_MODULE

    offenders = []
    in_repo = 0
    for name, path in loaded.items():
        if not path:
            continue
        try:
            relative = Path(path).resolve().relative_to(_REPO_ROOT)
        except ValueError:
            continue  # 저장소 밖(표준 라이브러리·site-packages)은 이 검사 대상이 아니다
        in_repo += 1
        if relative.parts and relative.parts[0] in ("references", "scripts", "tests"):
            offenders.append(f"{name} → {relative}")

    assert in_repo > 0, "저장소 안 모듈이 0건이면 이 테스트는 공허하다"
    # 이름 앵커 — in_repo 는 .venv 안 패키지로도 채워질 수 있어 개수만으로는 약하다.
    assert anchor in loaded
    assert offenders == [], f"운영 closure 가 금지 경로의 모듈을 끌고 있다: {offenders}"


@pytest.mark.parametrize("closure", ["core", "lane"])
def test_no_dev_token_literal_in_any_production_closure_source(
    closure: str, tmp_path: Path
) -> None:
    """closure 전체 소스에 dev 토큰 리터럴이 없다 — 기존 파일 1개 검사를 확대한다.

    Core 진입점과 platform lane closure **둘 다** 스캔한다. lane 쪽에는 워커의
    Bearer 토큰을 세팅하던 ``core_client`` 등 surviving 모듈이 들어간다 — 거기
    dev 토큰 기본값이 들어가도 Core-only 스캔은 통과하므로 둘 다 본다.
    """
    if closure == "core":
        loaded = _dump_closure(_CORE_BODY, tmp_path, env=_valid_env(tmp_path))
        anchor = _ANCHOR_MODULE
    else:
        loaded = _dump_closure(_LANE_BODY, tmp_path)
        anchor = _LANE_ANCHOR_MODULE

    scanned = 0
    scanned_names = set()
    for name, path in loaded.items():
        if not path or not name.startswith("ksi_"):
            continue
        source_path = Path(path)
        if not source_path.is_file():
            continue
        source = source_path.read_text(encoding="utf-8", errors="replace")
        scanned += 1
        scanned_names.add(name)
        for literal in _DEV_TOKEN_LITERALS:
            assert literal not in source, f"{name} 에 dev 토큰 리터럴이 있다: {literal!r}"
        assert "import run_core_dev" not in source, f"{name} 이 run_core_dev 를 import 한다"
        assert "from run_core_dev" not in source, f"{name} 이 run_core_dev 에서 import 한다"

    assert scanned > 0, "스캔한 파일이 0건이면 이 테스트는 공허하다"
    # 원래 사각지대였던 파일이 실제로 스캔 목록에 들어왔는지 못박는다.
    assert anchor in scanned_names


# ── 빌드 컨텍스트: 실행 가능한 dev 조립이 운영 이미지에 실리지 않는다 ──────────
#
# import closure 게이트는 "무엇이 로드되는가"를 보지 "이미지에 무엇이 들어있는가"를
# 보지 않는다. 둘은 다른 축이다 — 로드되지 않아도 이미지 안에 있으면 누군가 실행할
# 수 있다. 2026-08-18 적대적 검증이 실제로 이 구멍을 찾았다: .dockerignore 가
# scripts/ 를 빼지 않아 dev 고정 토큰 5개를 든 run_core_dev.py 가 운영 이미지에
# 그대로 실리고 있었다.

# 처리 워커 이미지는 P3 Task 3 에서 archive 로 분리됐다 — 운영 빌드 컨텍스트
# 게이트는 Core 이미지만 고정한다.
_DOCKERFILES = ("Dockerfile",)


def _dockerignore_entries() -> set[str]:
    text = (_REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def test_dev_assembly_tree_is_excluded_from_the_build_context() -> None:
    """dev 조립·테스트 트리가 .dockerignore 로 빠진다.

    Core Dockerfile 이 ``COPY . .`` 로 저장소 전체를 넣으므로, 제외는
    .dockerignore 한 곳에서만 일어난다 — 그 사실도 함께 고정한다.
    """
    for name in _DOCKERFILES:
        content = (_REPO_ROOT / name).read_text(encoding="utf-8")
        assert "COPY . ." in content, f"{name} 의 COPY 범위가 바뀌었다 — 이 게이트를 재검토하라"

    entries = _dockerignore_entries()
    for required in ("scripts/", "tests/"):
        assert required in entries, (
            f".dockerignore 에 {required} 가 없다 — 운영 이미지에 dev 조립이 실린다"
        )


def test_no_executable_dev_assembly_survives_the_build_context() -> None:
    """dev 토큰을 든 **실행 가능한 조립**이 빌드 컨텍스트에 남지 않는다.

    문서·예시 문자열(``tools/*.py`` docstring 의 사용 예)까지 금지하지는 않는다 —
    막아야 할 것은 "dev 자격증명으로 앱을 세우는 실행 경로"이지 문자열 자체가
    아니다. 그 경계를 여기서 명시한다.
    """
    excluded_roots = {entry.rstrip("/") for entry in _dockerignore_entries()}
    survivors = []
    for path in _REPO_ROOT.rglob("*.py"):
        try:
            relative = path.relative_to(_REPO_ROOT)
        except ValueError:  # pragma: no cover - rglob 는 항상 하위 경로다
            continue
        if not relative.parts or relative.parts[0] in excluded_roots:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if any(literal in source for literal in _DEV_TOKEN_LITERALS) and (
            "create_app(" in source or "assemble_app(" in source
        ):
            survivors.append(str(relative))

    assert survivors == [], (
        f"dev 자격증명으로 앱을 조립하는 파일이 빌드 컨텍스트에 남았다: {survivors}"
    )
