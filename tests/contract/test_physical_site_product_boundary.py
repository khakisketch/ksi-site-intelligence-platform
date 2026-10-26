"""Task1 product-boundary contract: Physical Site Intelligence vs acquisition.

ADR-KSI-039 is the accepted boundary: flight, autonomous acquisition,
tactical perception/control, and customer production reconstruction are
outside long-term Site Intelligence responsibility. Their sources remain
retained transitional implementation until a verified successor move.

Preservation is pinned by literal SHA256 digests of the two untouched
sections (historical Milestones and current product-state Current slice) taken at baseline
738b4a950e6b202a3a65982cea570e3a2ba4c8b7, plus the exact registry
status/state mapping by path — no Git-history access at test runtime, so
shallow-CI checkouts are safe. No invented status enum is accepted: the
mapping must equal the pinned snapshot exactly.
"""

import hashlib
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
PRODUCT_STATE_HISTORY = "docs/superpowers/product-state-history-2026-10-26.md"
PHASE_REGISTRY = "docs/goals/PHASE_REGISTRY.yaml"
ROADMAP = "docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md"
ADR036 = "docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md"
ADR037 = "docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md"
ADR038 = "docs/architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md"

# Literal baseline digests (sha256 of the section-normalized text below) taken
# from 738b4a950e6b202a3a65982cea570e3a2ba4c8b7 before any authority edit.
# Witness: fix1-logs/baseline-digests.txt in the task scratch folder.
MILESTONES_SHA256 = (
    "08c3d0ae2b0e707d3d32c565d666d1add2ca08d8e61eb6f299c607e49c6d1231"
)
CURRENT_SLICE_SHA256 = (
    "42ac39a86f4fe6d95edf4e5ca425472333e29acff2e103099cdc385248058993"
)

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

# Acquisition-only future slices: out-of-product on their own Next-slice line,
# never relabelled done. Historical Milestones rows are preserved separately.
EXCLUDED_FUTURE_IDS = [
    "autonomous-acquisition-closed-loop",
    "aol-1-capture-auto-ingest",
    "aol-1-mission-to-aircraft-delivery",
    "aol-3-terrain-aware-planning",
    "field-0-ground-integration",
    "field-0a-kmz-acceptance",
    "field-1-first-mapping-flight",
    "field-2-reobservation-loop-field",
    "field-3-terrain-aware-flight",
    "decision-psdk-flight-execution-authorization",
    "decision-flight-ceiling-reference-split",
    "flight-execution-c2-s1-upload-only",
    "flight-execution-c2-s2-propellerless-start",
    "flight-execution-c2-s3-supervised-flight",
    "flight-execution-c2-s4-routine-operation",
    "field-1-ground-control",
    "terrain-aware-planning-software",
    "terrain-aware-planning-field-acceptance",
    "track-a",
    "track-b",
]

MARKER = "out-of-product"
MARKER_SUFFIX = (
    " — **out-of-product** per ADR-KSI-039 "
    "(planning reference only; never a completion candidate)"
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if line.startswith(start))
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


def _assert_next_slice_markers(state_text: str) -> None:
    section = _section(state_text, "## Next slices", "## Backlog")
    lines = section.splitlines()
    for item in EXCLUDED_FUTURE_IDS:
        matches = [line for line in lines if line.startswith(f"- {item}:")]
        assert matches, item
        assert any(MARKER in line for line in matches), item


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
    assert "책임 밖" in _read(CONSTITUTION)

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
    goals = _section(prd, "## 3.1 제품 목표", "## ")
    assert "ADR-KSI-039" in goals
    assert "out-of-product" in goals
    assert "transitional" in goals or "역사적" in goals

    vertical = _section(prd, "## 23.1 첫 번째 Vertical", "## ")
    assert "ADR-KSI-039" in vertical
    assert "역사적" in vertical

    phases = _section(prd, "# 25. 구현 단계", "# 26.")
    assert "ADR-KSI-039" in phases
    assert "out-of-product" in phases

    completion = _section(prd, "# 26. 제품 완료 기준", "END-OF-PRD")
    assert "ADR-KSI-039" in completion
    assert "out-of-product" in completion
    # Useful reliability/governance content is preserved, not labelled obsolete.
    assert "Mock·Placeholder" in completion
    assert "License Registry" in completion


def test_constitution_and_ledger_passages_carry_scope() -> None:
    constitution = _read(CONSTITUTION)
    assert constitution.count("적용 범위(ADR-KSI-039)") >= 3
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

    # Dated Milestones moved to history; the literal preservation digest stays
    # unchanged. Current slice remains at the live path with its original hash.
    state = _read(PRODUCT_STATE)
    history = _section(_read(PRODUCT_STATE_HISTORY), "## Milestones", "## Current slice")
    assert hashlib.sha256(history.encode()).hexdigest() == MILESTONES_SHA256
    assert (
        hashlib.sha256(_section(state, "## Current slice", "## ").encode()).hexdigest()
        == CURRENT_SLICE_SHA256
    )

    # Historical Milestones rows are preserved as history, separately from marking.
    for item in EXCLUDED_FUTURE_IDS:
        assert item in history, item
    assert "false_positive_complete" in history


def test_open_acceptance_is_not_relabelled_done() -> None:
    state = _read(PRODUCT_STATE)
    assert "ADR-KSI-039" in state
    assert "out-of-product" in state
    _assert_next_slice_markers(state)

    # Retained customer gate stays open with KSI-side scope, not a marker.
    pilot = next(
        line
        for line in state.splitlines()
        if line.startswith("- pilot-default-external-reconstruction-release:")
    )
    assert "registration" in pilot and "inspection" in pilot
    assert "excluded" in pilot

    # Mixed tracks scope acquisition-only pieces instead of whole-track deletion.
    for track in ("- phase-4:", "- phase-5:"):
        line = next(ln for ln in state.splitlines() if ln.startswith(track))
        assert "acquisition-only pieces" in line, track

    # Registry keeps every status/state value pinned; no new enum allowed.
    registry_text = _read(PHASE_REGISTRY)
    assert "ADR-KSI-039" in registry_text
    assert _status_snapshot(yaml.safe_load(registry_text)) == EXPECTED_REGISTRY_STATUSES

    roadmap = _read(ROADMAP)
    assert "ADR-KSI-039" in roadmap
    assert "out-of-product" in roadmap


@pytest.mark.parametrize("item", EXCLUDED_FUTURE_IDS)
def test_excluded_next_slice_line_marked(item: str) -> None:
    section = _section(_read(PRODUCT_STATE), "## Next slices", "## Backlog")
    matches = [line for line in section.splitlines() if line.startswith(f"- {item}:")]
    assert matches, item
    assert any(MARKER in line for line in matches), item


def test_dropping_a_marker_is_detected() -> None:
    """Test-only mutation proof: removing one marker fails the check."""
    text = _read(PRODUCT_STATE)
    mutated = text.replace(MARKER_SUFFIX, "", 1)
    assert mutated != text
    with pytest.raises(AssertionError):
        _assert_next_slice_markers(mutated)
