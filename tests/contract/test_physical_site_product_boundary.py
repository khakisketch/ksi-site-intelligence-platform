"""Task1 product-boundary contract: Physical Site Intelligence vs acquisition.

ADR-KSI-039 is the accepted boundary: flight, autonomous acquisition,
tactical perception/control, and customer production reconstruction are
outside long-term Site Intelligence responsibility. Their sources remain
retained transitional implementation until a verified successor move.

These tests pin current-vs-history routing: active authority must name the
boundary, historical evidence and EXT-VAL acceptance must stay byte-identical
to the base revision, and excluded future work must read out-of-product,
never completed.
"""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

ADR039 = (
    "docs/architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md"
)
CONSTITUTION = "docs/product/PRODUCT_CONSTITUTION.md"
LEDGER = "docs/product/FINAL_DECISION_LEDGER_v1.0.md"
PRD = "docs/product/MASTER_PRD_v3.0.md"
INVARIANTS = "docs/product/DOMAIN_INVARIANTS.md"
READ_FIRST = "docs/00_READ_FIRST.md"
DOC_STATUS = "docs/DOCUMENT_STATUS.md"
DOCS_README = "docs/README.md"
OVERVIEW = "docs/architecture/00_SYSTEM_OVERVIEW.md"
ROOT_README = "README.md"
AGENTS = "AGENTS.md"
REPO_STRUCTURE = "REPOSITORY_STRUCTURE.md"
PRODUCT_STATE = "docs/superpowers/product-state.md"
PHASE_REGISTRY = "docs/goals/PHASE_REGISTRY.yaml"
ROADMAP = "docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md"
ADR036 = "docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md"
ADR037 = "docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md"
ADR038 = "docs/architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md"

# Foundation task start revision: authority/history comparisons pin to this base.
BASE_REVISION = "738b4a9"

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

# Acquisition-only future slices: out-of-product, never relabelled done.
EXCLUDED_FUTURE_IDS = [
    "autonomous-acquisition-closed-loop",
    "aol-1-capture-auto-ingest",
    "aol-1-mission-to-aircraft-delivery",
    "aol-3-terrain-aware-planning",
    "field-0-ground-integration",
    "field-1-first-mapping-flight",
    "field-2-reobservation-loop-field",
    "field-3-terrain-aware-flight",
    "decision-psdk-flight-execution-authorization",
    "flight-execution-c2-s1-upload-only",
    "flight-execution-c2-s2-propellerless-start",
    "flight-execution-c2-s3-supervised-flight",
    "flight-execution-c2-s4-routine-operation",
    "field-1-ground-control",
    "terrain-aware-planning-software",
    "terrain-aware-planning-field-acceptance",
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _at_base(rel: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{BASE_REVISION}:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _section(text: str, start: str, end: str) -> str:
    lines = text.splitlines()
    begin = next(i for i, line in enumerate(lines) if line.startswith(start))
    stop = next(
        (i for i, line in enumerate(lines) if i > begin and line.startswith(end)),
        len(lines),
    )
    return "\n".join(lines[begin:stop]) + "\n"


def test_current_authority_excludes_long_term_acquisition() -> None:
    adr = _read(ADR039)
    assert "## Current responsibility" in adr
    responsibility = _section(adr, "## Current responsibility", "## ")
    assert "xternal" in responsibility and "collect" in responsibility
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
    status = _read(DOC_STATUS)
    assert "ADR-KSI-039" in status
    assert "ADR-039" in status or "ADR-KSI-039" in status

    # Unchanged EXT-VAL acceptance and historical milestone evidence match base.
    current_state = _read(PRODUCT_STATE)
    base_state = _at_base(PRODUCT_STATE)
    assert _section(current_state, "## Current slice", "## ") == _section(
        base_state, "## Current slice", "## "
    )
    assert _section(current_state, "## Milestones", "## Current slice") == _section(
        base_state, "## Milestones", "## Current slice"
    )


def test_open_acceptance_is_not_relabelled_done() -> None:
    state = _read(PRODUCT_STATE)
    assert "ADR-KSI-039" in state
    assert "out-of-product" in state

    # Excluded future slices are still listed with open statuses, never done.
    milestones = _section(state, "## Milestones", "## Current slice")
    for item in EXCLUDED_FUTURE_IDS:
        assert item in milestones, item
    assert "false_positive_complete" in milestones  # history preserved, not rewritten

    registry_text = _read(PHASE_REGISTRY)
    assert "ADR-KSI-039" in registry_text
    registry = yaml.safe_load(registry_text)
    assert registry["axes"]["autonomous_acquisition"]["state"] == "BLOCKED"
    assert (
        registry["terrain_aware_planning"]["software_status"] == "NOT_IMPLEMENTED"
    )
    # No invented status enum: only statuses the existing consumers use.
    allowed = {"PLANNED", "IN_PROGRESS", "GATED", "DONE", "BLOCKED",
               "COMPLETED", "PROPOSED", "NOT_IMPLEMENTED", "NOT_VERIFIED",
               "PAUSED_BY_USER", "ACCEPTED", "APPROVED", "SOFTWARE_PREPARED",
               "PASS", "COMPLETE", "PARTIAL", "DEFERRED", "ACTIVE"}
    statuses = set()

    def _collect(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"status", "direction_status", "execution_status",
                           "design_status", "software_status",
                           "physical_acceptance_status"} and isinstance(value, str):
                    statuses.add(value)
                _collect(value)
        elif isinstance(node, list):
            for entry in node:
                _collect(entry)

    _collect(registry)
    assert statuses <= allowed, sorted(statuses - allowed)

    roadmap = _read(ROADMAP)
    assert "ADR-KSI-039" in roadmap
    assert "out-of-product" in roadmap
