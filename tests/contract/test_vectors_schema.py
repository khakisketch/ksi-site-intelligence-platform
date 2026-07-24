"""Golden test vector 파일 스키마 검증 (P0-3).

`packages/test-vectors/vectors/{legacy_compat,ksi_correctness}/*.json` 전체가 CLAUDE.md
착수 spec 이 요구하는 필수 metadata 를 갖추는지 검증한다:

- `legacy_compat/*.json` → `source`{repo,commit,file} 필수(참고 구현 실행 캡처의 출처).
- `ksi_correctness/*.json` → `derivation`("analytic") + `derivation_basis`(산출 근거) 필수
  (source 대신).
- 공통 필수: `extraction`{script, runtime}, `tolerance`{abs, rel, rationale}, `cases`(비어
  있지 않은 배열, 각 원소는 id/description/input/output 을 가지며 id 는 파일 내 유일).

이 테스트는 이 워커가 만든 벡터뿐 아니라 다른 워커가 소유한
`legacy_compat/telemetry_interpolation.json` 도 함께 검증한다(모든 벡터 파일이 같은
계약을 지켜야 loader.py 가 카테고리 전체를 균일하게 다룰 수 있다) — 그 파일의 *내용*은
건드리지 않고 읽기만 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from ksi_test_vectors.loader import Category, list_vectors, load_vector_file

VECTORS_ROOT = (
    Path(__file__).resolve().parents[2] / "packages" / "test-vectors" / "vectors"
)
CATEGORIES: tuple[Category, ...] = ("legacy_compat", "ksi_correctness")


def _all_vector_files() -> list[tuple[Category, Path]]:
    files: list[tuple[Category, Path]] = []
    for category in CATEGORIES:
        directory = VECTORS_ROOT / category
        if not directory.is_dir():
            continue
        files.extend((category, p) for p in sorted(directory.glob("*.json")))
    return files


_VECTOR_FILES = _all_vector_files()
_VECTOR_IDS = [f"{cat}/{path.name}" for cat, path in _VECTOR_FILES]


def test_at_least_one_vector_file_per_category() -> None:
    for category in CATEGORIES:
        names = list_vectors(category)
        assert names, f"{category} 아래 벡터 파일이 하나도 없음"


@pytest.mark.parametrize("category,path", _VECTOR_FILES, ids=_VECTOR_IDS)
def test_vector_file_has_required_metadata(category: Category, path: Path) -> None:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    # ── source(legacy_compat) XOR derivation(ksi_correctness) ──────────────
    has_source = "source" in raw
    has_derivation = "derivation" in raw
    assert has_source != has_derivation, (
        f"{path}: source 와 derivation 은 상호배타적으로 정확히 하나만 있어야 함"
        f" (source={has_source}, derivation={has_derivation})"
    )

    if category == "legacy_compat":
        assert has_source, f"{path}: legacy_compat 벡터는 source 필수(참고 구현 캡처 출처)"
        source = raw["source"]
        assert isinstance(source, dict)
        for key in ("repo", "commit", "file"):
            assert isinstance(source.get(key), str) and source[key], (
                f"{path}: source.{key} 는 비어있지 않은 문자열이어야 함"
            )
    else:  # ksi_correctness
        assert has_derivation, f"{path}: ksi_correctness 벡터는 derivation 필수(source 대신)"
        assert raw["derivation"] == "analytic", f"{path}: derivation 은 'analytic' 이어야 함"
        basis = raw.get("derivation_basis")
        assert isinstance(basis, str) and basis, (
            f"{path}: derivation_basis(손 계산 가능한 산출 근거)가 비어있지 않은 문자열이어야 함"
        )

    # ── extraction ───────────────────────────────────────────────────────────
    assert "extraction" in raw, f"{path}: extraction 메타데이터 필수"
    extraction = raw["extraction"]
    assert isinstance(extraction, dict)
    assert isinstance(extraction.get("script"), str) and extraction["script"], (
        f"{path}: extraction.script 필수"
    )
    runtime = extraction.get("runtime")
    assert isinstance(runtime, dict), f"{path}: extraction.runtime 은 dict 여야 함"
    assert isinstance(runtime.get("language"), str) and runtime["language"], (
        f"{path}: extraction.runtime.language 필수(python|node 등)"
    )
    version_keys = ("version", "python", "node")
    assert any(isinstance(runtime.get(k), str) and runtime[k] for k in version_keys), (
        f"{path}: extraction.runtime 에 실제 실행 버전({version_keys} 중 하나) 필수"
    )
    assert isinstance(runtime.get("runner"), str) and runtime["runner"], (
        f"{path}: extraction.runtime.runner(어떤 러너로 실행했는지) 필수"
    )

    # ── tolerance ────────────────────────────────────────────────────────────
    assert "tolerance" in raw, f"{path}: tolerance 메타데이터 필수"
    tolerance = raw["tolerance"]
    assert isinstance(tolerance, dict)
    assert isinstance(tolerance.get("abs"), (int, float)), f"{path}: tolerance.abs 는 숫자"
    assert isinstance(tolerance.get("rel"), (int, float)), f"{path}: tolerance.rel 는 숫자"
    rationale = tolerance.get("rationale")
    assert isinstance(rationale, str) and len(rationale) >= 20, (
        f"{path}: tolerance.rationale(선정 근거)이 실질적인 설명 문자열이어야 함(20자 이상)"
    )
    by_field = tolerance.get("by_field")
    if by_field is not None:
        assert isinstance(by_field, dict), f"{path}: tolerance.by_field 는 dict 여야 함"
        for field_name, override in by_field.items():
            assert isinstance(override, dict), (
                f"{path}: tolerance.by_field.{field_name} 는 dict 여야 함"
            )
            assert "abs" in override or "rel" in override, (
                f"{path}: tolerance.by_field.{field_name} 는 abs 또는 rel 을 가져야 함"
            )

    # ── cases ────────────────────────────────────────────────────────────────
    assert "cases" in raw, f"{path}: cases 배열 필수"
    cases = raw["cases"]
    assert isinstance(cases, list) and cases, f"{path}: cases 는 비어있지 않은 배열이어야 함"

    seen_ids: set[str] = set()
    for case in cases:
        assert isinstance(case, dict), f"{path}: 각 case 는 dict 여야 함"
        case_id = case.get("id")
        assert isinstance(case_id, str) and case_id, f"{path}: case.id 는 비어있지 않은 문자열"
        assert case_id not in seen_ids, f"{path}: case id 중복 - {case_id}"
        seen_ids.add(case_id)

        description = case.get("description")
        assert isinstance(description, str) and description, (
            f"{path}: case[{case_id}].description 필수"
        )
        assert "input" in case, f"{path}: case[{case_id}].input 필수(값이 None이어도 키는 필수)"
        assert "output" in case, f"{path}: case[{case_id}].output 필수(값이 None이어도 키는 필수)"


@pytest.mark.parametrize("category,path", _VECTOR_FILES, ids=_VECTOR_IDS)
def test_loader_parses_vector_file(category: Category, path: Path) -> None:
    """loader.py 가 실제로 이 파일을 예외 없이 파싱해 VectorFile 로 반환하는지(스모크)."""
    vector_file = load_vector_file(category, path.stem)

    assert vector_file.category == category
    assert vector_file.cases, f"{path}: 파싱된 cases 가 비어있음"
    assert vector_file.tolerance.abs >= 0
    assert vector_file.tolerance.rel >= 0

    if category == "legacy_compat":
        assert vector_file.source is not None
    else:
        assert vector_file.derivation == "analytic"

    # id 로 임의 케이스 1건 재조회가 되는지(case() 헬퍼 계약).
    first_case = vector_file.cases[0]
    assert vector_file.case(first_case.id) is first_case


def test_loader_list_vectors_matches_filesystem() -> None:
    for category in CATEGORIES:
        expected = sorted(
            p.stem for p in (VECTORS_ROOT / category).glob("*.json")
        )
        assert list_vectors(category) == expected


def test_loader_unknown_case_id_raises_keyerror() -> None:
    category, path = _VECTOR_FILES[0]
    vector_file = load_vector_file(category, path.stem)
    with pytest.raises(KeyError):
        vector_file.case("__definitely_not_a_real_case_id__")
