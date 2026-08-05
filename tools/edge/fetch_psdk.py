"""DJI Payload SDK(PSDK) 명시적 fetch — ``edge/third_party/PSDK_LOCK.yaml`` 기반.

런타임 자동 다운로드는 하지 않는다 — PSDK는 이 스크립트로만 받는다. ``models/`` +
``tools/fetch_model.py``와 동일한 정신이다: 계보(핀 SHA·라이선스 판단)는 git에
커밋하고, 실물(소스+사전 컴파일 바이너리)은 gitignored 디렉터리에 명시적으로
받는다. ``PSDK_LOCK.yaml``의 ``pinned_commit``으로 체크아웃한 뒤, 대표 파일의
sha256을 락 파일과 대조해 핀 이탈(브랜치 강제 push, 태그 리라이트 등)을 잡는다.

사용법::

    uv run python tools/edge/fetch_psdk.py
    uv run python tools/edge/fetch_psdk.py --dest edge/third_party/psdk

받은 트리는 ``edge/third_party/psdk/``에 놓인다(``.gitignore``로 제외됨).
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

import yaml

DEFAULT_LOCK_PATH = Path(__file__).resolve().parents[2] / "edge" / "third_party" / "PSDK_LOCK.yaml"
DEFAULT_DEST = Path(__file__).resolve().parents[2] / "edge" / "third_party" / "psdk"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def fetch(lock_path: Path, dest: Path) -> int:
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    repo = lock["source"]["repo"]
    pinned_commit = lock["source"]["pinned_commit"]

    if dest.exists() and (dest / ".git").is_dir():
        current = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if current == pinned_commit:
            print(f"✓ {dest} 이미 핀 커밋({pinned_commit[:12]})에 있음 — fetch 생략")
        else:
            print(f"기존 {dest}가 다른 커밋({current[:12]})에 있음 — 핀 커밋으로 재체크아웃")
            _run(["git", "-C", str(dest), "fetch", "origin", pinned_commit])
            _run(["git", "-C", str(dest), "checkout", "--quiet", pinned_commit])
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"clone: {repo} -> {dest}")
        _run(["git", "clone", "--quiet", repo, str(dest)])
        _run(["git", "-C", str(dest), "checkout", "--quiet", pinned_commit])

    # 핀 이탈 감지 — 대표 파일의 sha256이 락과 다르면 즉시 실패한다(잘못된 커밋/
    # 리라이트된 히스토리가 로컬에 남아 다음 사람을 속이는 것을 막는다 —
    # tools/fetch_model.py와 동일한 fail-fast 원칙).
    # 대조 대상을 한 곳에 모은다 — 셋 다 락 파일이 계보로 기록한 값이므로 전부
    # 검증한다(2026-08-04 감사: 이전에는 verified_files만 봐서, 실제 링크 대상인
    # libpayloadsdk.a와 라이선스 판단 근거인 LICENSE.txt/EULA.txt가 무검증이었다 —
    # 라이선스 근거 파일이 바뀌어도 아무 코드가 막지 않는 상태였다).
    checks: dict[str, str] = {}
    checks.update(lock.get("verified_files") or {})
    checks.update((lock.get("license") or {}).get("verified_files") or {})
    target_lib_rel = lock["target"]["library_path"]
    target_lib_sha = lock["target"].get("library_sha256_on_device")
    if target_lib_sha:
        checks[target_lib_rel] = target_lib_sha

    if not checks:
        # 공집합을 "전부 일치"로 통과시키면 검사 미수행이 성공으로 위장된다.
        print(
            "✗ 락 파일에 대조할 sha256 항목이 하나도 없다 — 핀 이탈을 감지할 수 없다.",
            file=sys.stderr,
        )
        return 1

    mismatches: list[str] = []
    for rel_path, expected_sha in checks.items():
        target = dest / rel_path
        if not target.is_file():
            mismatches.append(f"{rel_path}: 파일 없음(핀 커밋에 존재하지 않음)")
            continue
        actual_sha = _sha256(target)
        if actual_sha != expected_sha:
            mismatches.append(f"{rel_path}: sha256 불일치(기대 {expected_sha}, 실제 {actual_sha})")

    if mismatches:
        print("✗ 핀 이탈 감지 — fetch 실패:", file=sys.stderr)
        for m in mismatches:
            print(f"    {m}", file=sys.stderr)
        return 1

    target_lib = dest / target_lib_rel
    if not target_lib.is_file():
        print(f"✗ 타깃 라이브러리 없음: {target_lib}", file=sys.stderr)
        return 1

    version = lock["source"].get("observed_version", "?")
    print(f"✓ PSDK {version} @ {pinned_commit[:12]} 확보 완료: {dest}")
    print(f"  라이선스: {lock['license']['spdx']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH, help="PSDK_LOCK.yaml 경로")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="PSDK를 받을 디렉터리")
    args = parser.parse_args(argv)
    return fetch(args.lock, args.dest)


if __name__ == "__main__":
    raise SystemExit(main())
