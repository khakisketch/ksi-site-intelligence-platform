"""tools/fetch_test_assets.py — 재인코딩 저장이 항상 ``<target>.part`` 임시
경로(``_digest.fetch_with_digest_verification``)에 쓰인다는 점을 놓치고
``Image.save()`` 에 ``format=`` 없이 호출하면, Pillow 가 확장자 ``.part`` 로
포맷을 추론하려다 ``ValueError: unknown file extension: .part`` 로 죽는다는
회귀[High/correctness]를 고정한다.

네트워크 I/O 는 ``urllib.request.urlopen`` 을 스텁으로 바꿔 없앤다 — 이 테스트가
검증하는 것은 원격 자산 내용이 아니라 로컬 재인코딩·저장 경로 자체다.
"""

from __future__ import annotations

import hashlib
import sys
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fetch_test_assets  # noqa: E402 -- 위 sys.path 조작 뒤에만 해석 가능


def _make_source_png_bytes() -> bytes:
    """원격에서 받은 원본 취급할 작은 이미지 — 포맷은 PNG 로 인코딩해 확장자와
    무관하게 내용 기반으로 열린다는 것을 같이 확인한다(재인코딩 출력 확장자는
    ledger 의 asset 이름, 즉 ``.jpg`` 다)."""
    buf = BytesIO()
    Image.new("RGB", (10, 10), color=(200, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


def _expected_reencoded_sha256(raw: bytes) -> str:
    """fetch_test_assets._fetch_and_reencode 와 동일한 변환(RGB 변환 · 800px
    thumbnail · JPEG q92)을 독립적으로 재현해 기대 digest 를 구한다."""
    image = Image.open(BytesIO(raw)).convert("RGB")
    image.thumbnail((800, 800))
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=92)
    return hashlib.sha256(buf.getvalue()).hexdigest()


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


def test_fetch_reencodes_and_saves_without_pil_format_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[회귀] 재인코딩 저장 경로가 항상 ``.part`` 임시 파일이어도 ``fetch()`` 가
    ``ValueError: unknown file extension`` 없이 끝까지 성공한다."""
    raw = _make_source_png_bytes()
    expected_sha256 = _expected_reencoded_sha256(raw)

    ledger_path = tmp_path / "TEST_ASSETS.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "assets": [
                    {
                        "name": "red.jpg",
                        "sha256": expected_sha256,
                        "role": "regression fixture",
                        "source_url": "http://example.invalid/red.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    dest_dir = tmp_path / "dest"

    monkeypatch.setattr(fetch_test_assets, "LEDGER", ledger_path)
    monkeypatch.setattr(fetch_test_assets, "DEST", dest_dir)
    monkeypatch.setattr(
        fetch_test_assets.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(raw),
    )

    exit_code = fetch_test_assets.fetch()

    assert exit_code == 0
    saved = dest_dir / "red.jpg"
    assert saved.is_file()
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == expected_sha256
    # 실제로 JPEG 로 저장됐는지(포맷 인자가 먹었는지)까지 확인.
    with Image.open(saved) as reopened:
        assert reopened.format == "JPEG"


def test_unmapped_suffix_raises_clear_error_instead_of_silent_pil_guess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """확장자가 ``_PIL_FORMAT_BY_SUFFIX`` 에 없는 미지원 자산은 Pillow 의
    (틀릴 수 있는) 확장자 추론에 맡기지 않고 즉시 명확한 에러로 죽는다."""
    raw = _make_source_png_bytes()

    ledger_path = tmp_path / "TEST_ASSETS.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "assets": [
                    {
                        "name": "red.gif",
                        "sha256": "0" * 64,
                        "role": "regression fixture",
                        "source_url": "http://example.invalid/red.gif",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    dest_dir = tmp_path / "dest"

    monkeypatch.setattr(fetch_test_assets, "LEDGER", ledger_path)
    monkeypatch.setattr(fetch_test_assets, "DEST", dest_dir)
    monkeypatch.setattr(
        fetch_test_assets.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(raw),
    )

    with pytest.raises(ValueError, match="알 수 없는 확장자"):
        fetch_test_assets.fetch()
    assert not (dest_dir / "red.gif").exists()
