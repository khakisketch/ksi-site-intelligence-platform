"""manifoldctl DPK 서브커맨드 — PSDK vendored build_dpk.sh 호출 배선 + dji_app_ctl
위임 인자 검증 (Track A/B PSDK 정적 개발, 2026-08-06).

``package`` 는 실기 없이 종단까지(진짜 .dpk 생성) 검증 가능하다. ``install``/
``uninstall``/``start``/``stop``/``restart``/``list``/``status <app>`` 는
dji_app_ctl 을 SSH 로 위임하므로 **실행 자체**(mf_ssh 왕복)는 이 스위트가 검증하지
않는다 — 인자 검증(필수 인자 누락·잘못된 확장자)만 실기 없이 확인한다. 위임하는
명령 문자열 자체는 실기 HIL 세션(2026-08-03,
hil_raw_logs/SESS-20260803T125616Z-PENDING-SN/01_env_inventory/
20260803T125944Z__psdk_discovery.log)에서 ``dji_app_ctl --help`` 로 실측한
시그니처를 그대로 옮긴 것이다 — 지어낸 명령이 아니다. 다만 설치→재시작→정상기동
까지 실제로 동작하는지(HARDWARE_SESSION_PLAYBOOK.md §8)는 별도 HIL 검증이 아직
없다.

app.json 은 이 저장소가 지어내지 않는다 — PSDK vendored 샘플
(edge/third_party/psdk/samples/sample_c/platform/linux/manifold3/app_json/app.json)
을 그대로 픽스처로 쓰고, ``bin`` 필드만 테스트 임시 디렉터리의 더미 실행파일로
바꾼다(user_app_id "164884" 는 DJI 공식 데모 앱 ID — 실제 자격증명이 아니다).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFOLDCTL = _REPO_ROOT / "scripts" / "manifold" / "manifoldctl"
_SAMPLE_APP_JSON = (
    _REPO_ROOT
    / "edge"
    / "third_party"
    / "psdk"
    / "samples"
    / "sample_c"
    / "platform"
    / "linux"
    / "manifold3"
    / "app_json"
    / "app.json"
)

_requires_psdk_tree = pytest.mark.skipif(
    not _SAMPLE_APP_JSON.is_file(),
    reason="PSDK vendored tree 없음(tools/edge/fetch_psdk.py로 받아야 함) — CI 기본 미설치",
)


def _run_manifoldctl(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_MANIFOLDCTL), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _fixture_app_json(tmp_path: Path) -> Path:
    """실물 PSDK 샘플 app.json 을 그대로 쓰되 bin 필드만 임시 더미 실행파일로 바꾼다.

    build_dpk.sh 는 ``bin``/``userconfig`` 를 **항상** app.json 디렉터리 기준
    상대경로로 취급한다(``input_json_dir/$bin_file`` 로 조립 — 절대경로를 줘도
    그대로 접두된다). 그래서 파일명만 적고 app.json 과 같은 디렉터리에 둔다.
    """
    data = json.loads(_SAMPLE_APP_JSON.read_text(encoding="utf-8"))
    bin_name = "dummy_app_binary"
    bin_path = tmp_path / bin_name
    bin_path.write_text("#!/bin/sh\necho dummy\n", encoding="utf-8")
    bin_path.chmod(0o755)
    data["bin"] = bin_name
    data["userconfig"] = []
    app_json_path = tmp_path / "app.json"
    app_json_path.write_text(json.dumps(data), encoding="utf-8")
    return app_json_path


def test_package_requires_app_json_flag(tmp_path: Path) -> None:
    result = _run_manifoldctl("package", cwd=tmp_path)
    assert result.returncode != 0
    assert "--app-json" in result.stderr


def test_package_rejects_missing_app_json_file(tmp_path: Path) -> None:
    result = _run_manifoldctl(
        "package", "--app-json", str(tmp_path / "does-not-exist.json"), cwd=tmp_path
    )
    assert result.returncode != 0
    assert "app.json 파일이 없다" in result.stderr


@_requires_psdk_tree
def test_package_rejects_unknown_flag(tmp_path: Path) -> None:
    app_json = _fixture_app_json(tmp_path)
    result = _run_manifoldctl(
        "package", "--bogus-flag", "x", "--app-json", str(app_json), cwd=tmp_path
    )
    assert result.returncode != 0
    assert "알 수 없는 인자" in result.stderr


@_requires_psdk_tree
def test_package_invokes_build_dpk_and_produces_dpk_file(tmp_path: Path) -> None:
    """[핵심] 실제 PSDK vendored build_dpk.sh 를 호출해 진짜 .dpk 를 만든다 — 배선이
    실제로 동작하는지를 목킹 없이 증명한다(green≠작동)."""
    app_json = _fixture_app_json(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    result = _run_manifoldctl(
        "package", "--app-json", str(app_json), "-o", str(output_dir), cwd=tmp_path
    )
    assert result.returncode == 0, result.stdout + result.stderr
    dpk_files = list(output_dir.glob("*.dpk"))
    assert dpk_files, f"outputs: {list(output_dir.iterdir())}, stdout={result.stdout}"


# ── dji_app_ctl 위임 서브커맨드 — 인자 검증만(SSH 왕복은 실기 종속이라 범위 밖) ──


@pytest.mark.parametrize("subcmd", ["install", "uninstall", "start", "stop", "restart"])
def test_delegated_subcommand_requires_argument(subcmd: str, tmp_path: Path) -> None:
    result = _run_manifoldctl(subcmd, cwd=tmp_path)
    assert result.returncode != 0
    assert "사용법" in result.stderr


def test_install_rejects_missing_file(tmp_path: Path) -> None:
    result = _run_manifoldctl("install", str(tmp_path / "nope.dpk"), cwd=tmp_path)
    assert result.returncode != 0
    assert "파일이 없다" in result.stderr


def test_install_rejects_non_dpk_extension(tmp_path: Path) -> None:
    not_a_dpk = tmp_path / "notadpk.txt"
    not_a_dpk.write_text("x", encoding="utf-8")
    result = _run_manifoldctl("install", str(not_a_dpk), cwd=tmp_path)
    assert result.returncode != 0
    assert ".dpk 파일이 아니다" in result.stderr


def test_unknown_subcommand_lists_dpk_commands_in_usage(tmp_path: Path) -> None:
    result = _run_manifoldctl("bogus-subcommand", cwd=tmp_path)
    assert result.returncode != 0
    assert "install" in result.stderr
    assert "uninstall" in result.stderr


@_requires_psdk_tree
def test_package_fails_closed_when_psdk_tree_missing(tmp_path: Path) -> None:
    """PSDK vendored 트리가 없으면(gitignored, fetch 안 한 상태) 명확한 사유로 거부한다."""
    app_json = _fixture_app_json(tmp_path)
    fake_repo = tmp_path / "fake-repo"
    fake_manifold_dir = fake_repo / "scripts" / "manifold"
    fake_manifold_dir.mkdir(parents=True)
    (fake_repo / "edge" / "manifold-runtime").mkdir(parents=True)
    for name in ("manifoldctl", "lib.sh", "manifold.env.example"):
        shutil.copy(_REPO_ROOT / "scripts" / "manifold" / name, fake_manifold_dir / name)
    fake_manifoldctl = fake_manifold_dir / "manifoldctl"
    fake_manifoldctl.chmod(0o755)

    result = subprocess.run(
        [str(fake_manifoldctl), "package", "--app-json", str(app_json)],
        cwd=fake_repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "PSDK vendored tree가 없다" in result.stderr
