"""Task1 product-boundary contract: Physical Site Intelligence vs acquisition.

ADR-KSI-039 is the accepted boundary: flight, autonomous acquisition,
tactical perception/control, and customer production reconstruction are
outside long-term Site Intelligence responsibility. Their sources remain
retained transitional implementation until a verified successor move.

Preservation is pinned by the exact registry status/state mapping by path
taken at baseline 738b4a950e6b202a3a65982cea570e3a2ba4c8b7 — no Git-history
access at test runtime, so shallow-CI checkouts are safe. No invented status
enum is accepted: the mapping must equal the pinned snapshot exactly.

The simplified canon product-state owns a single "## Next slice" section:
obsolete PRD acquisition phases create no executable or active product scope
(ADR-KSI-039). The retired per-ID "## Next slices" out-of-product markers left
with that deleted section and are not re-pinned here.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

ADR039 = (
    "docs/architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md"
)
CONSTITUTION = "docs/product/PRODUCT_CONSTITUTION.md"
LEDGER = "docs/product/FINAL_DECISION_LEDGER_v1.0.md"
PRD = "docs/product/MASTER_PRD_v3.0.md"
INVARIANTS = "docs/product/DOMAIN_INVARIANTS.md"
DOC_STATUS = "docs/DOCUMENT_STATUS.md"
OVERVIEW = "docs/architecture/00_SYSTEM_OVERVIEW.md"
REPO_STRUCTURE = "REPOSITORY_STRUCTURE.md"
PRODUCT_STATE = "docs/superpowers/product-state.md"
PHASE_REGISTRY = "docs/goals/PHASE_REGISTRY.yaml"
ROADMAP = "docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md"
ADR036 = "docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md"
ADR037 = "docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md"
ADR038 = "docs/architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md"

# Exact registry status/state mapping by dotted path at the same baseline.
EXPECTED_REGISTRY_STATUSES = {
    "axes.autonomous_acquisition.state": "BLOCKED",
    "axes.site_intelligence_core.state": "ACTIVE",
    "confirmed_next_improvements.status": "IN_PROGRESS",
    "confirmed_next_improvements.workstreams[0].status": "IN_PROGRESS",
    "confirmed_next_improvements.workstreams[1].status": "GATED",
    "confirmed_next_improvements.workstreams[2].status": "GATED",
    "confirmed_next_improvements.workstreams[3].status": "GATED",
    "confirmed_next_improvements.workstreams[4].status": "GATED",
    "confirmed_next_improvements.workstreams[5].status": "GATED",
    "confirmed_next_improvements.workstreams[6].status": "SOFTWARE_PREPARED",
    "operations_console_delivery.phases[0].status": "DONE",
    "operations_console_delivery.phases[1].status": "DONE",
    "operations_console_delivery.phases[2].status": "DONE",
    "operations_console_delivery.phases[3].stages[0].status": "BLOCKED",
    "operations_console_delivery.phases[3].stages[1].status": "BLOCKED",
    "operations_console_delivery.phases[3].status": "BLOCKED",
    "operations_console_delivery.phases[4].status": "PLANNED",
    "operations_console_delivery.phases[5].status": "PLANNED",
    "phases[0].status": "IN_PROGRESS",
    "phases[1].status": "DONE",
    "phases[2].status": "IN_PROGRESS",
    "phases[3].status": "IN_PROGRESS",
    "phases[4].status": "IN_PROGRESS",
    "phases[5].status": "BLOCKED",
    "repository_normalization.status": "DONE",
    "spatial_data_platform.direction_status": "ACCEPTED",
    "spatial_data_platform.execution_status": "PAUSED_BY_USER",
    "spatial_data_platform.status": "PLANNED",
    "terrain_aware_planning.current_goal_status": "COMPLETED",
    "terrain_aware_planning.design_status": "APPROVED",
    "terrain_aware_planning.future_goals[0].status": "PROPOSED",
    "terrain_aware_planning.future_goals[1].status": "PROPOSED",
    "terrain_aware_planning.physical_acceptance_status": "NOT_VERIFIED",
    "terrain_aware_planning.software_status": "NOT_IMPLEMENTED",
}

# Authoritative Physical Site definition shared verbatim by Constitution/PRD.
SHARED_DEFINITION = (
    "물리적 현장의 관측을 사람·외부 에이전트·소프트웨어·로보틱스가 재사용하는 "
    "근거형 Site State와 Change로 바꾸는 기반이다"
)
SHARED_NONEXCLUSIVE = "건설·토공 운영이 첫 시장이며, 플랫폼의 배타적 정체성이 아니다"
LINEAGE_INVARIANTS = ("INV-040", "INV-050", "INV-051", "INV-053", "INV-060", "INV-061")

# Invariants that stay effective in their applicable domains per the boundary.
EFFECTIVE_INVARIANTS = [
    "INV-020",
    "INV-024",
    "INV-040",
    "INV-050",
    "INV-051",
    "INV-053",
    "INV-054",
    "INV-055",
    "INV-060",
    "INV-061",
]

# Simplified canon (2026-11-11 rewrite): product-state owns a single
# "## Next slice" section. This sentence replaces the retired per-ID
# "## Next slices" out-of-product markers, which left with that deleted
# section: obsolete acquisition phase IDs create no executable scope.
# (product-state.md: "Obsolete PRD acquisition phases do not create
# executable or active product scope (ADR-KSI-039)".)
OBSOLETE_PHASES_SENTENCE = (
    "Obsolete PRD acquisition phases do not create executable or active product scope"
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if line.startswith(start))
    if not end:
        stop = len(lines)
    else:
        stop = next(
            (i for i, line in enumerate(lines) if i > begin and line.startswith(end)),
            len(lines),
        )
    return "\n".join(lines[begin:stop]) + "\n"


def _status_snapshot(node: object, path: str = "") -> dict:
    snapshot: dict = {}
    if isinstance(node, dict):
        for key, value in node.items():
            dotted = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and (
                key == "status" or key == "state" or key.endswith("_status")
            ):
                snapshot[dotted] = value
            snapshot.update(_status_snapshot(value, dotted))
    elif isinstance(node, list):
        for index, entry in enumerate(node):
            snapshot.update(_status_snapshot(entry, f"{path}[{index}]"))
    return snapshot


def _assert_next_slice_boundary(state_text: str) -> None:
    section = _section(state_text, "## Next slice", "## Backlog")
    assert OBSOLETE_PHASES_SENTENCE in section
    assert "ADR-KSI-039" in section


def _assert_pilot_gate_open(state_text: str) -> None:
    # Retained customer gate stays open with KSI-side scope, not a marker.
    pilot = next(
        line
        for line in state_text.splitlines()
        if "pilot first-release gate" in line
    )
    assert "remains open" in pilot
    assert "registration" in pilot and "inspection" in pilot
    assert "excluded" in pilot


def test_current_authority_excludes_long_term_acquisition() -> None:
    adr = _read(ADR039)
    assert "## Current responsibility" in adr
    responsibility = _section(adr, "## Current responsibility", "## ")
    assert "External collectors" in responsibility
    assert "KSI Core" in responsibility
    assert "state" in responsibility.lower() or "evidence" in responsibility.lower()
    assert "outside long-term" in adr

    # Active authority links the new boundary.
    assert "ADR-KSI-039" in _read(CONSTITUTION)
    assert "ADR-KSI-039" in _read(LEDGER)
    assert "ADR-KSI-039" in _read(PRD)
    # Simplified canon: the rewritten constitution routes the acquisition
    # boundary ("장기 취득 장비의 제품 책임 경계는 [ADR-KSI-039]를 따른다",
    # wrapped across two lines on disk) instead of repeating the exclusion
    # phrase; the live exclusion wording is PRD §1
    # ("현 플랫폼 책임 밖이다(ADR-KSI-039)").
    constitution_text = _read(CONSTITUTION)
    assert "장기 취득 장비의 제품 책임" in constitution_text
    assert "경계는 [ADR-KSI-039]" in constitution_text

    # ADR039's cited authority targets resolve; links are not dangling.
    for target in (CONSTITUTION, LEDGER, PRD, ADR036, ADR037, ADR038):
        assert (ROOT / target).exists(), target

    # Effective platform/external invariants stay named in the boundary.
    for invariant in EFFECTIVE_INVARIANTS:
        assert invariant in adr, invariant


def test_physical_site_definition_agrees() -> None:
    constitution = _read(CONSTITUTION)
    prd = _read(PRD)
    # Authoritative definition names Physical Site observations, not only
    # external reconstructed data, and Constitution and PRD agree verbatim.
    assert SHARED_DEFINITION in constitution
    assert SHARED_DEFINITION in prd
    assert SHARED_NONEXCLUSIVE in constitution
    assert SHARED_NONEXCLUSIVE in prd
    # Data delivery and fixed analysis stay the existing product paths.
    assert "데이터 제공" in constitution
    assert "고정 분석" in constitution or "고정된 분석" in constitution
    assert "데이터 제공" in prd or "데이터 경로" in prd


def test_prd_goals_and_completion_are_scoped() -> None:
    prd = _read(PRD)
    # Simplified canon: the "## 3.1 제품 목표" section is gone; product scope now
    # lives in "## 1. 제품 정체성 및 범위", which carries the live exclusion
    # ("현 플랫폼 책임 밖이다(ADR-KSI-039)") and the tech-adoption boundary
    # ("원본 사진 처리·매핑·재구성 엔진 개발 및 실행은 제외한다 ... 범위 밖이다",
    # with historical managed/test profiles kept as history, not requirements).
    scope = _section(prd, "## 1. 제품 정체성 및 범위", "## ")
    assert "현 플랫폼 책임 밖이다" in scope
    assert "ADR-KSI-039" in scope
    assert "범위 밖이다" in scope
    assert "역사적" in scope

    vertical = _section(prd, "## 23.1 첫 번째 Vertical", "## ")
    # Simplified canon rewords the first-vertical line ("첫 검증 시장"; the old
    # "첫 실증 시장" phrasing is gone with the rewrite).
    assert "첫 검증 시장" in vertical
    assert "별도 수락" in vertical

    # Simplified canon: platform acceptance (§25) owns the ADR-KSI-039 completion
    # exclusion and names both acceptance series; the old "P-AC not in
    # completion" pin is inverted by the rewrite (completion now judges by
    # "현재 slice와 P-AC").
    acceptance_scope = _section(prd, "# 25. 제품·플랫폼 수락", "# ")
    assert "ADR-KSI-039" in acceptance_scope
    assert "완료조건이 아니다" in acceptance_scope
    assert "P-AC" in acceptance_scope and "EXT-VAL" in acceptance_scope

    completion = _section(prd, "# 26. 제품 완료와 미수락 조건", "")
    assert "현재 slice" in completion and "host/customer acceptance" in completion
    assert "실제 근거" in completion
    # Existing contracts, not a separate PRD checklist, own acceptance details.
    acceptance = _read("docs/acceptance/CIVIL_PROCESSING_V1_ACCEPTANCE.md")
    assert "survey-grade" in acceptance and "field acceptance" in acceptance
    for invariant in LINEAGE_INVARIANTS:
        assert invariant in _read(INVARIANTS)


def test_constitution_and_ledger_passages_carry_scope() -> None:
    # Simplified canon: the rewritten constitution no longer repeats
    # per-passage "적용 범위(ADR-KSI-039)" labels; it routes the boundary once
    # ("장기 취득 장비의 제품 책임 경계는 [ADR-KSI-039]를 따른다", wrapped
    # across two lines on disk) and names ADR-KSI-039 as the current
    # acquisition responsibility boundary in its approval section.
    constitution = _read(CONSTITUTION)
    assert "장기 취득 장비의 제품 책임" in constitution
    assert "경계는 [ADR-KSI-039]" in constitution
    assert constitution.count("ADR-KSI-039") >= 2
    ledger = _read(LEDGER)
    assert ledger.count("적용 범위(ADR-KSI-039)") >= 2


def test_external_collection_is_not_a_platform_runtime_dependency_claim() -> None:
    adr = _read(ADR039)
    assert "not a platform runtime dependency" in adr

    # Current runtime tables distinguish retained transitional implementation
    # from target responsibility; no source moves in this task.
    assert "transitional implementation" in _read(REPO_STRUCTURE)
    assert "transitional implementation" in _read(OVERVIEW)
    assert "ADR-KSI-039" in _read(REPO_STRUCTURE)
    assert "ADR-KSI-039" in _read(OVERVIEW)


def test_historical_decisions_have_explicit_supersession() -> None:
    adr = _read(ADR039)
    assert "## Supersession scope" in adr
    scope = _section(adr, "## Supersession scope", "## ")
    for name in ("Constitution", "Decision Ledger", "MASTER_PRD", "ADR-KSI-037", "ADR-KSI-038"):
        assert name in scope, name

    # Older ADRs keep dated evidence; they gain a routing pointer, not a rewrite.
    assert "ADR-KSI-039" in _read(ADR037)
    assert "ADR-KSI-039" in _read(ADR038)

    # Routing index marks the boundary active.
    assert "ADR-KSI-039" in _read(DOC_STATUS)

    # Current product scope is enforced from the live product slice and
    # accepted phase registry; retired milestone narratives are not authority.
    state = _read(PRODUCT_STATE)
    assert "EXT-VAL-01" in state and "EXT-VAL-08" in state
    _assert_next_slice_boundary(state)
    assert _status_snapshot(yaml.safe_load(_read(PHASE_REGISTRY))) == EXPECTED_REGISTRY_STATUSES


def test_open_acceptance_is_not_relabelled_done() -> None:
    state = _read(PRODUCT_STATE)
    assert "ADR-KSI-039" in state
    assert "out-of-product" in state
    _assert_next_slice_boundary(state)

    # Simplified canon: the pilot first-release gate line owns the open gate;
    # the retired per-ID "- <id>:" marker lines left with "## Next slices".
    _assert_pilot_gate_open(state)

    # Platform and any remaining shared phases keep acquisition excluded and
    # spatial/inspection work in scope under the accepted responsibility split.
    for track in ("- phase-3:", "- phase-4:", "- phase-5:"):
        line = next((ln for ln in state.splitlines() if ln.startswith(track)), None)
        if line is not None:
            assert "acquisition-only pieces" in line or "ADR-KSI-039" in line, track

    # Registry keeps every status/state value pinned; no new enum allowed.
    registry_text = _read(PHASE_REGISTRY)
    assert "ADR-KSI-039" in registry_text
    assert _status_snapshot(yaml.safe_load(registry_text)) == EXPECTED_REGISTRY_STATUSES

    roadmap = _read(ROADMAP)
    assert "ADR-KSI-039" in roadmap
    assert "customer/data rights and operational gates" in roadmap
    assert "active acceptance or task-selection authority" in roadmap
    for invariant in ("INV-040", "INV-051", "INV-053", "INV-060", "INV-061"):
        assert invariant in _read(INVARIANTS)


def test_obsolete_phases_create_no_executable_scope() -> None:
    section = _section(_read(PRODUCT_STATE), "## Next slice", "## Backlog")
    assert OBSOLETE_PHASES_SENTENCE in section
    assert "ADR-KSI-039" in section
    # The retired per-ID "## Next slices" section is gone; no per-ID marker
    # lines are required or re-pinned here.
    assert "## Next slices" not in _read(PRODUCT_STATE)


def test_removing_active_exclusion_is_detected() -> None:
    """Test-only mutation proof: dropping the exclusion sentence fails the check."""
    text = _read(PRODUCT_STATE)
    mutated = text.replace(OBSOLETE_PHASES_SENTENCE, "", 1)
    assert mutated != text
    with pytest.raises(AssertionError):
        _assert_next_slice_boundary(mutated)


def test_closing_open_acceptance_is_detected() -> None:
    """Test-only mutation proof: the pilot gate must read as open, not done."""
    text = _read(PRODUCT_STATE)
    mutated = text.replace("remains open", "is done", 1)
    assert mutated != text
    with pytest.raises(AssertionError):
        _assert_pilot_gate_open(mutated)
