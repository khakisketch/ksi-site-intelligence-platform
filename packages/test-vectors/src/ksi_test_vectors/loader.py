"""Golden test vector 로더 (P0-3).

`packages/test-vectors/vectors/{legacy_compat,ksi_correctness}/*.json` 을 읽어
metadata(source|derivation, extraction, tolerance)와 케이스 배열을 타입 있는
dataclass 로 반환한다.

- `legacy_compat/`: 참고 구현(Scout/Platform) 실행 캡처 — 필수 metadata: `source`.
- `ksi_correctness/`: 손으로 계산 가능한 해석적 진리 — 필수 metadata: `derivation`.

두 카테고리 모두 `extraction`(어떻게 값을 만들었는가)과 `tolerance`(얼마나 벌어져도
같다고 볼 것인가 + 그 근거)는 필수다. 이 로더는 스키마를 강제하지 않는다
(강제는 `tests/contract/test_vectors_schema.py` 담당) — 여기는 순수 파싱 편의만 제공한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Category = Literal["legacy_compat", "ksi_correctness"]

# packages/test-vectors/src/ksi_test_vectors/loader.py 기준 3단계 위 = packages/test-vectors/
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
VECTORS_ROOT = _PACKAGE_ROOT / "vectors"


@dataclass(frozen=True, slots=True)
class SourceMeta:
    """`legacy_compat` 벡터의 원천 참고 구현 좌표."""

    repo: str
    commit: str
    file: str


@dataclass(frozen=True, slots=True)
class ExtractionMeta:
    """캡처/도출에 쓴 스크립트와 실행 환경."""

    script: str
    runtime: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToleranceMeta:
    """비교 허용오차 + 선정 근거. `by_field` 는 필드별 override(없으면 최상위 abs/rel 적용)."""

    abs: float
    rel: float
    rationale: str
    by_field: dict[str, dict[str, float]] = field(default_factory=dict)

    def for_field(self, field_name: str) -> tuple[float, float]:
        """필드별 (abs, rel) — override 없으면 최상위 기본값으로 폴백."""
        override = self.by_field.get(field_name)
        if override is None:
            return self.abs, self.rel
        return float(override.get("abs", self.abs)), float(override.get("rel", self.rel))


@dataclass(frozen=True, slots=True)
class VectorCase:
    """벡터 파일의 케이스 1건."""

    id: str
    description: str
    input: Any
    output: Any
    api: str | None = None
    tag: str | None = None


@dataclass(frozen=True, slots=True)
class VectorFile:
    """벡터 JSON 파일 1개(파일당 하나의 원천/파생 함수 묶음)."""

    category: Category
    name: str
    path: Path
    source: SourceMeta | None
    derivation: str | None
    derivation_basis: str | None
    extraction: ExtractionMeta
    tolerance: ToleranceMeta
    cases: list[VectorCase]

    def case(self, case_id: str) -> VectorCase:
        """id 로 케이스 1건 조회. 없으면 KeyError(명확한 실패 — 조용한 None 금지)."""
        for c in self.cases:
            if c.id == case_id:
                return c
        msg = f"case '{case_id}' not found in {self.category}/{self.name}"
        raise KeyError(msg)


def _parse_source(raw: dict[str, Any] | None) -> SourceMeta | None:
    if raw is None:
        return None
    return SourceMeta(repo=str(raw["repo"]), commit=str(raw["commit"]), file=str(raw["file"]))


def _parse_extraction(raw: dict[str, Any]) -> ExtractionMeta:
    return ExtractionMeta(script=str(raw["script"]), runtime=dict(raw["runtime"]))


def _parse_tolerance(raw: dict[str, Any]) -> ToleranceMeta:
    return ToleranceMeta(
        abs=float(raw["abs"]),
        rel=float(raw["rel"]),
        rationale=str(raw.get("rationale", "")),
        by_field={k: dict(v) for k, v in raw.get("by_field", {}).items()},
    )


def _parse_case(raw: dict[str, Any]) -> VectorCase:
    return VectorCase(
        id=str(raw["id"]),
        description=str(raw.get("description", "")),
        input=raw.get("input"),
        output=raw.get("output"),
        api=raw.get("api"),
        tag=raw.get("tag"),
    )


def vector_path(category: Category, name: str) -> Path:
    """category/name(확장자 있든 없든) → 실제 JSON 파일 경로."""
    stem = name[:-5] if name.endswith(".json") else name
    return VECTORS_ROOT / category / f"{stem}.json"


def list_vectors(category: Category) -> list[str]:
    """category 아래 벡터 파일 이름(확장자 제외) 목록, 정렬됨. 디렉토리 없으면 빈 목록."""
    directory = VECTORS_ROOT / category
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def load_vector_file(category: Category, name: str) -> VectorFile:
    """벡터 JSON 파일 1개를 읽어 `VectorFile` 로 파싱한다.

    `source`/`derivation` 은 상호배타적이지 않게 파싱한다(둘 다 없거나 하나만 있는 것이
    정상) — 어느 쪽이 필수인지 강제하는 것은 이 함수의 책임이 아니라
    `tests/contract/test_vectors_schema.py` 의 책임이다.
    """
    path = vector_path(category, name)
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return VectorFile(
        category=category,
        name=path.stem,
        path=path,
        source=_parse_source(raw.get("source")),
        derivation=raw.get("derivation"),
        derivation_basis=raw.get("derivation_basis"),
        extraction=_parse_extraction(raw["extraction"]),
        tolerance=_parse_tolerance(raw["tolerance"]),
        cases=[_parse_case(c) for c in raw["cases"]],
    )


def load_all(category: Category) -> list[VectorFile]:
    """category 아래 모든 벡터 파일을 이름순으로 로드."""
    return [load_vector_file(category, name) for name in list_vectors(category)]
