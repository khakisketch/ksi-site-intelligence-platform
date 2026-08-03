"""저장소 위생 가드(scripts/check_repo_hygiene.sh)가 실제로 위반을 잡는지 검증한다.

green≠작동 방지 핵심: "스크립트가 0을 반환한다"가 아니라 **"위반을 주입하면 실제로
실패하고, 제거하면 통과한다"**(변이 테스트)를 확인한다. 이 저장소는 과거 러너에
ripgrep이 없어 reference 가드가 조용한 no-op이 된 사고를 겪었고(감사 #29), 그 이후
"검사 미수행 ≠ 통과" 를 규율로 삼는다 — 이 파일이 규칙 4·5·6에 대해 그 규율을 집행한다.

ADR-KSI-009 §D6의 "이 4규칙은 수동 변이 확인만 수행했다(자동 회귀 테스트는 아직
없다)" 서술을 해소하기 위해 2026-08-04 신설. 각 테스트는 임시 파일을 git index에
`add -f`로 넣었다가(gitignore를 일부러 우회해 규칙 자체를 태운다) 반드시 되돌린다.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pytest


class TrackedFileFactory(Protocol):
    """위반 파일을 만들어 git index에 넣는 픽스처의 호출 시그니처."""

    def __call__(self, relative_name: str, content: str) -> Path: ...


REPO_ROOT = Path(__file__).resolve().parents[2]
HYGIENE_SCRIPT = REPO_ROOT / "scripts" / "check_repo_hygiene.sh"
# 위반 주입 위치 — 어느 경로든 규칙이 걸려야 하므로 실제 소스 트리 안에 만든다.
SCRATCH_DIR = REPO_ROOT / "tests" / "contract" / "_hygiene_mutation_scratch"


def _define_line(macro: str, value: str) -> str:
    """`#define <macro> "<value>"` 한 줄을 **런타임에 조립**한다.

    소스에 리터럴로 적으면 이 테스트 파일 자체가 규칙5(실값 탐지)에 걸려
    check_repo_hygiene.sh 가 저장소를 영구히 실패시킨다 — 실제로 2026-08-04에
    그렇게 만들어 게이트가 자기 자신을 잡는 것을 확인하고 이 헬퍼로 교체했다.
    (가드에 테스트 파일 예외를 두는 방식은 채택하지 않았다 — 예외는 곧 우회로다.)
    """
    return f"#{'define'} {macro}   \"{value}\"\n"


def _run_hygiene() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HYGIENE_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )


@pytest.fixture
def tracked_file() -> Iterator[TrackedFileFactory]:
    """임시 파일을 git index에 강제로 넣었다가 반드시 되돌리는 픽스처.

    `add -f`로 gitignore를 우회하는 이유: 규칙 4·6은 gitignore와 위생 가드가 이중
    방어인데, gitignore에 막혀 index에 못 들어가면 정작 **가드 자체**는 한 번도
    실행되지 않는다. 여기서 검증하려는 건 두 번째 방어선이므로 일부러 우회한다.
    """
    created: list[Path] = []

    def _make(relative_name: str, content: str) -> Path:
        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        path = SCRATCH_DIR / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git("add", "-f", str(path.relative_to(REPO_ROOT)))
        created.append(path)
        return path

    yield _make

    for path in created:
        _git("reset", "-q", str(path.relative_to(REPO_ROOT)))
        path.unlink(missing_ok=True)
    if SCRATCH_DIR.exists():
        for child in sorted(SCRATCH_DIR.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink(missing_ok=True)
        SCRATCH_DIR.rmdir()


class TestBaseline:
    def test_clean_tree_passes(self) -> None:
        """위반이 없으면 통과한다 — 이게 아니면 아래 변이 테스트가 무의미하다."""
        result = _run_hygiene()
        assert result.returncode == 0, f"기준선이 이미 실패한다:\n{result.stdout}\n{result.stderr}"


class TestRule4GeneratedHeader:
    def test_tracked_dji_sdk_app_info_header_is_rejected(
        self, tracked_file: TrackedFileFactory
    ) -> None:
        tracked_file("dji_sdk_app_info.h", '#define USER_APP_ID "your_app_id"\n')
        result = _run_hygiene()
        assert result.returncode != 0
        assert "생성 헤더" in result.stdout

    def test_uppercase_variant_is_also_rejected(self, tracked_file: TrackedFileFactory) -> None:
        """대소문자 변형이 우회로가 되지 않아야 한다(2026-08-04 감사 지적 → grep -i)."""
        tracked_file("DJI_SDK_APP_INFO.H", '#define USER_APP_ID "your_app_id"\n')
        result = _run_hygiene()
        assert result.returncode != 0


class TestRule5CredentialLiteral:
    def test_placeholder_value_is_allowed(self, tracked_file: TrackedFileFactory) -> None:
        """플레이스홀더는 오탐하지 않는다 — 오탐하면 개발자가 가드를 끄게 된다."""
        tracked_file("ph.h", '#define USER_APP_KEY   "your_app_key"\n')
        result = _run_hygiene()
        assert result.returncode == 0, f"플레이스홀더 오탐:\n{result.stdout}"

    def test_empty_value_is_allowed(self, tracked_file: TrackedFileFactory) -> None:
        """빈 문자열도 유출이 아니다(초기 구현은 이걸 오탐했다)."""
        tracked_file("empty.h", '#define USER_APP_KEY   ""\n')
        result = _run_hygiene()
        assert result.returncode == 0, f"빈 값 오탐:\n{result.stdout}"

    def test_real_looking_value_is_rejected(self, tracked_file: TrackedFileFactory) -> None:
        tracked_file("leak.h", _define_line("USER_APP_KEY", "FAKEKEY0000deadbeef0000FAKEKEY"))
        result = _run_hygiene()
        assert result.returncode != 0
        assert "실값" in result.stdout

    def test_value_starting_with_your_prefix_is_still_rejected(
        self, tracked_file: TrackedFileFactory
    ) -> None:
        """zero-width lookahead 우회 차단 — 'your_'로 시작해도 실값이면 잡아야 한다."""
        tracked_file("sneaky.h", _define_line("USER_APP_KEY", "your_company_realkey123"))
        result = _run_hygiene()
        assert result.returncode != 0

    def test_license_field_is_covered_not_just_key(self, tracked_file: TrackedFileFactory) -> None:
        """DJI 원본 샘플의 검사 코드는 LICENSE 자리에 BAUD_RATE를 비교하는 오타가
        있어 License 플레이스홀더를 검증하지 못한다 — 우리 가드는 둘 다 봐야 한다."""
        tracked_file("lic.h", _define_line("USER_APP_LICENSE", "FAKELICENSE0000notarealvalue"))
        result = _run_hygiene()
        assert result.returncode != 0

    def test_tab_separator_is_covered(self, tracked_file: TrackedFileFactory) -> None:
        tracked_file("tabbed.h", '#define\tUSER_APP_KEY\t"realvalue123"\n')
        result = _run_hygiene()
        assert result.returncode != 0

    def test_multiline_define_is_rejected_because_value_cannot_be_scanned(
        self,
        tracked_file: TrackedFileFactory,
    ) -> None:
        """백슬래시 개행 형태는 라인 단위 grep이 값을 볼 수 없다 — 값 판정 불가이므로
        형태 자체를 금지한다(규칙 5b). 통과시키면 실값 스캔의 우회로가 된다."""
        tracked_file("multi.h", '#define USER_APP_KEY  \\\n  "realvalue123"\n')
        result = _run_hygiene()
        assert result.returncode != 0
        assert "여러 줄" in result.stdout


class TestRule6DpkArtifact:
    def test_tracked_dpk_is_rejected(self, tracked_file: TrackedFileFactory) -> None:
        tracked_file("app.dpk", "binary-ish\n")
        result = _run_hygiene()
        assert result.returncode != 0
        assert "DPK" in result.stdout

    def test_uppercase_dpk_extension_is_also_rejected(
        self, tracked_file: TrackedFileFactory
    ) -> None:
        """대문자 확장자가 우회로가 되지 않아야 한다(2026-08-04 감사 지적 → grep -i)."""
        tracked_file("app.DPK", "binary-ish\n")
        result = _run_hygiene()
        assert result.returncode != 0
