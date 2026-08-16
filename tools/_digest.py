"""공용 다운로드+digest 검증 — ``tools/`` 아래 fetch 스크립트 여럿이 각자 손으로
짜던 "임시 파일로 받고, digest 가 맞아야만 최종 이름으로 원자적으로 바꾼다"는
절차를 한 곳에 모은다.

다운로드 방식(HTTP/gdown/이미지 재인코딩)은 스크립트마다 다르므로 여기서 정하지
않는다 — 그건 ``fetch_fn`` 콜백으로 주입받는다. 이 모듈이 책임지는 것은 그
방식과 무관하게 항상 같아야 하는 절차뿐이다: 임시 파일에 받고, digest 를
재확인하고, 통과했을 때만 자리를 바꾸고, 실패·중단 잔여물은 항상 지운다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path


def sha256_file(path: Path) -> str:
    """파일의 SHA-256 hex digest — 청크(1MB) 단위로 읽어 대용량 파일도 전체를
    메모리에 올리지 않는다."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DigestMismatchError(Exception):
    """받은 바이트의 digest 가 기대와 다르다 — 잘못된 변형이 로컬에 남아 다음
    사람을 속이는 것을 막기 위해, 이 예외가 나면 호출자는 target 을 만들지 않는다
    (``fetch_with_digest_verification`` 이 이미 임시 파일을 지운 뒤다)."""

    def __init__(self, name: str, *, expected: str, actual: str) -> None:
        self.name = name
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"{name}: 받은 파일 digest {actual[:12]}… ≠ 원장 {expected[:12]}… — 폐기함"
        )


def fetch_with_digest_verification(
    target: Path, expected_sha256: str, fetch_fn: Callable[[Path], None]
) -> None:
    """``fetch_fn(partial)`` 로 받은 뒤 digest 가 맞을 때만 ``partial`` 을
    ``target`` 으로 원자적으로 바꾼다.

    호출자가 "이미 있고 유효한지"는 미리 확인한다 — 이 함수는 그 판단을 하지
    않는다(호출자마다 "이미 있음"/"불일치, 다시 받는다" 안내 문구가 달라서다).
    이 함수가 유일하게 강제하는 것은: 실패(digest 불일치·``fetch_fn`` 예외)
    경로에서 ``target`` 이 절대 생기거나 바뀌지 않고, 임시 파일도 남지 않는다는
    것이다.

    Raises:
        DigestMismatchError: 받은 바이트의 digest 가 ``expected_sha256`` 과 다를 때.
        Exception: ``fetch_fn`` 이 던지는 그대로(네트워크 오류 등) — 여기서
            강등하지 않는다. 어느 경로든 ``finally`` 가 잔여물 정리를 보장한다.
    """
    partial = target.with_suffix(target.suffix + ".part")
    actual: str | None = None
    try:
        fetch_fn(partial)
        actual = sha256_file(partial)
        if actual != expected_sha256:
            raise DigestMismatchError(target.name, expected=expected_sha256, actual=actual)
    finally:
        # digest 미통과·중단 잔여물은 항상 제거(예외 경로 포함). 성공 시에는
        # 위에서 이미 구한 actual 을 재사용해 같은 파일을 두 번 해싱하지
        # 않는다 — fetch_fn 이 actual 계산 전에 예외를 던졌다면 actual 은
        # None 이고, 그 경우도 잔여물이므로 무조건 지운다.
        if partial.is_file() and actual != expected_sha256:
            partial.unlink()
    partial.replace(target)
