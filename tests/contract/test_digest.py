"""tools/_digest.py — fetch_model.py 등 6개 스크립트가 공유하는 "받고 검증하고
원자적으로 자리를 바꾼다" 절차의 계약 테스트.

이전에는 이 절차가 스크립트마다 손으로 다시 구현돼 있었고, 그중 어느 하나도
직접 테스트되지 않았다 — 검증 정책(불일치 시 폐기)을 한 곳이 몰래 빼먹어도
아무도 몰랐다. 여기서 세 갈래를 고정한다: 성공(원자적 교체) · 불일치(폐기,
target 은 손대지 않음) · fetch_fn 예외(전파, 잔여물 정리는 그대로 보장).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from _digest import (  # noqa: E402 -- 위 sys.path 조작 뒤에만 해석 가능
    DigestMismatchError,
    fetch_with_digest_verification,
    sha256_file,
)

_HELLO = b"hello world"
_HELLO_SHA256 = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_sha256_file_matches_known_vector(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(_HELLO)
    assert sha256_file(path) == _HELLO_SHA256


def test_sha256_file_reads_in_chunks_for_large_files(tmp_path: Path) -> None:
    """청크(1MB) 경계를 넘는 파일도 올바른 digest 를 낸다 — 전체를 한 번에
    읽지 않는다는 것 자체를 이 테스트로 증명하진 않지만, 청크 루프 로직이
    한 번의 read 로 끝나지 않는 크기에서도 맞는지는 고정한다."""
    import hashlib

    data = b"x" * (3 * (1 << 20) + 7)  # 3MB + 7바이트 — 청크 경계 불일치 유발
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_fetch_with_digest_verification_succeeds_and_replaces_atomically(
    tmp_path: Path,
) -> None:
    target = tmp_path / "model.bin"

    def _write_hello(partial: Path) -> None:
        partial.write_bytes(_HELLO)

    fetch_with_digest_verification(target, _HELLO_SHA256, _write_hello)

    assert target.read_bytes() == _HELLO
    assert not target.with_suffix(target.suffix + ".part").exists()


def test_digest_mismatch_discards_partial_and_leaves_target_untouched(
    tmp_path: Path,
) -> None:
    """[핵심 음성] 받은 바이트의 digest 가 원장과 다르면 target 을 만들지 않고,
    임시 파일도 남기지 않는다 — 잘못된 변형이 로컬에 남아 다음 사람을 속이는
    것을 막는 것이 이 모듈 전체의 존재 이유다."""
    target = tmp_path / "model.bin"

    def _write_wrong_bytes(partial: Path) -> None:
        partial.write_bytes(b"not the expected content")

    with pytest.raises(DigestMismatchError) as excinfo:
        fetch_with_digest_verification(target, _HELLO_SHA256, _write_wrong_bytes)

    assert excinfo.value.expected == _HELLO_SHA256
    assert not target.exists()
    assert not target.with_suffix(target.suffix + ".part").exists()


def test_preexisting_target_is_not_touched_when_verification_never_runs(
    tmp_path: Path,
) -> None:
    """이 함수 자체는 '이미 유효한지'를 판단하지 않는다(호출자 책임) — 그래도
    fetch_fn 이 실패하면 기존 target 이 훼손되지 않아야 한다."""
    target = tmp_path / "model.bin"
    target.write_bytes(_HELLO)

    def _boom(partial: Path) -> None:
        raise ConnectionError("network unreachable")

    with pytest.raises(ConnectionError):
        fetch_with_digest_verification(target, _HELLO_SHA256, _boom)

    assert target.read_bytes() == _HELLO


def test_fetch_fn_exception_propagates_and_cleans_up_partial_bytes(
    tmp_path: Path,
) -> None:
    """[핵심 음성][회귀] fetch_fn 이 부분 바이트를 쓴 채로 예외를 던지는 경우
    (네트워크 단절 등) — 원래 3개 스크립트 모두 이 상황을 try/finally 로
    막았다. 공용 함수가 그 보장을 이어받는다."""
    target = tmp_path / "model.bin"

    def _partial_write_then_boom(partial: Path) -> None:
        partial.write_bytes(b"truncated")
        raise ConnectionError("connection reset")

    with pytest.raises(ConnectionError):
        fetch_with_digest_verification(target, _HELLO_SHA256, _partial_write_then_boom)

    assert not target.exists()
    assert not target.with_suffix(target.suffix + ".part").exists()
