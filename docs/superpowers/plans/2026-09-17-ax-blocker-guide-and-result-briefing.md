# AX-1/AX-2: Blocker Guide and External Result Briefing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blocked external-use decisions explain themselves in Korean with a concrete next step, the external work-order stage reflects the real loop state, and every relative-volume report, review and approval records a deterministic site briefing surfaced on the site workspace, work order and Home.

**Architecture:** One versioned catalog under `contracts/` explains reason and remediation codes; Core proves coverage, the Dashboard renders it from a byte-identical generated copy. Briefings are deterministic projections written into the existing `SiteBriefingStore` by post-commit listeners on the volume store, review store and proposal service; the store is now created without the copilot, and the LLM refresh path stays copilot-gated.

**Tech Stack:** FastAPI/Pydantic Core with JSONL journals, Next.js/React dashboard, vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-17-ax-product-loop-design.md`

## Global Constraints

- AI never computes numbers, never issues, approves or plans a Mission, never emits flight coordinates; briefings copy sealed report values and may only subtract two retained net values.
- External AI stays OFF without the site's `aiEgressAllowed`; deterministic briefings never call a model.
- Briefings and drafts are append-only records with the source watermark they came from; a same-watermark briefing is never re-recorded.
- Organization isolation (INV-060): every read is scoped to the principal organization; foreign sites are indistinguishable from absent.
- New `/v1/*` paths must be documented in `contracts/api/openapi-core.yaml` with `security` (contract sync test).
- Korean copy in the UI; raw codes only in expert details.
- Run tests with `uv run --locked pytest -q -p no:cacheprovider <path>` from the repo root and `npm test -- <file>` from `apps/dashboard/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `contracts/catalogs/external-use-blockers.v1.json` | Catalog: reason and remediation codes → Korean title/explanation/step, owner, target |
| `services/core/src/ksi_core/domains/external/quantity/external_use_evaluator.py` | Exposes `PAIR_REASON_REMEDIATIONS` used by `_remediation` |
| `services/core/src/ksi_core/domains/external/quantity/external_use_blockers.py` | Loads and validates the catalog for Core (`load_external_use_blocker_catalog`) |
| `tests/contract/test_external_use_blockers.py` | Catalog coverage, shape and dashboard sync |
| `tools/sync_external_use_blockers.py` | Copies the catalog into the dashboard generated file |
| `apps/dashboard/src/lib/external-use-blockers.generated.json` | Byte-identical dashboard copy |
| `apps/dashboard/src/lib/external-use-blockers.ts` | `explainExternalUseDecision(reasons, remediations)` lookup with fallback |
| `apps/dashboard/src/components/external-results/ExternalUseBlockerCard.tsx` | Blocker card (why / what to do / owner / link) |
| `apps/dashboard/src/app/field/ExternalResultWorkflowPanel.tsx`, `ExternalEvidencePanel.tsx` | Render the card for BLOCKED decisions |
| `apps/dashboard/src/app/field/external-work-order-stage.ts` | `deriveExternalWorkOrderStage(input)` pure stage derivation |
| `apps/dashboard/src/app/field/work-orders/[workOrderId]/page.tsx` | Uses the stage for external orders |
| `services/core/src/ksi_core/domains/external/quantity/external_relative_volumes.py` | `bind_report_listener`, post-commit notify |
| `services/core/src/ksi_core/domains/external/workflow/external_result_reviews.py` | `bind_review_listener`, post-commit notify |
| `services/core/src/ksi_core/domains/external/workflow/external_reobservation_proposals.py` | `bind_approval_listener`, post-commit notify |
| `services/core/src/ksi_core/domains/external/workflow/external_result_briefings.py` | `ExternalResultBriefingProjector` |
| `services/core/src/ksi_core/domains/workspace/site_workspace.py` | `SiteBriefingStore.latest_for_organization`, router split (store vs service), org-wide latest route |
| `services/core/src/ksi_core/composition/workspace_graph.py`, `external_graph.py`, `assembly.py`, `assembly_validation.py`, `routes/operations.py`, `app_factory.py` | Wiring |
| `contracts/api/openapi-core.yaml` | `/v1/site-briefings/latest` |
| `apps/dashboard/src/lib/core-api/site-workspace.ts` | `listLatestSiteBriefings()` |
| `apps/dashboard/src/lib/home-operations.ts`, `apps/dashboard/src/app/page.tsx` | Home recent updates from external briefings |
| `apps/dashboard/src/app/sites/[siteId]/page.tsx` | Briefing card action gating |

---

### Task 1: Blocker catalog contract with Core coverage test

**Files:**
- Create: `contracts/catalogs/external-use-blockers.v1.json`
- Create: `services/core/src/ksi_core/domains/external/quantity/external_use_blockers.py`
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_use_evaluator.py` (`_remediation`, around line 1021)
- Test: `tests/contract/test_external_use_blockers.py`

**Interfaces:**
- Produces: `PAIR_REASON_REMEDIATIONS: dict[str, str]` (module constant in the evaluator), `load_external_use_blocker_catalog() -> ExternalUseBlockerCatalog` with `.reasons: dict[str, BlockerReason]` and `.remediations: dict[str, BlockerRemediation]`, `CATALOG_PATH: Path`.

- [ ] **Step 1: Write the failing test**

```python
"""Blocker catalog: every emitted reason/remediation is explained once, and the dashboard copy is identical."""

from __future__ import annotations

import json
from pathlib import Path

from ksi_core.domains.external.quantity.external_use_blockers import (
    CATALOG_PATH,
    load_external_use_blocker_catalog,
)
from ksi_core.domains.external.quantity.external_use_evaluator import PAIR_REASON_REMEDIATIONS

_REPO = Path(__file__).resolve().parents[2]
_DASHBOARD_COPY = _REPO / "apps/dashboard/src/lib/external-use-blockers.generated.json"
_OWNERS = {"OPERATOR", "ADMIN", "CUSTOMER"}
_TARGETS = {"SUBJECT", "INSPECTION", "DISPLAY", "POLICY", "EVIDENCE", "MAPPING", "ZONE", "HEIGHT", "GENERAL"}


def test_catalog_covers_every_evaluator_reason_and_remediation() -> None:
    catalog = load_external_use_blocker_catalog()
    assert catalog.contract_version == "external-use-blockers.v1"
    missing_reasons = set(PAIR_REASON_REMEDIATIONS) - set(catalog.reasons)
    missing_remediations = set(PAIR_REASON_REMEDIATIONS.values()) - set(catalog.remediations)
    assert not missing_reasons, missing_reasons
    assert not missing_remediations, missing_remediations
    assert "RESOLVE_EXTERNAL_USE_BLOCKER" in catalog.remediations


def test_catalog_entries_are_complete_korean_guidance() -> None:
    catalog = load_external_use_blocker_catalog()
    for code, reason in catalog.reasons.items():
        assert code.isupper() and reason.title.strip() and reason.explanation.strip(), code
        assert reason.owner in _OWNERS and reason.target in _TARGETS, code
    for code, remediation in catalog.remediations.items():
        assert code.isupper() and remediation.step.strip(), code
        assert remediation.owner in _OWNERS and remediation.target in _TARGETS, code


def test_dashboard_copy_is_byte_identical_to_the_contract() -> None:
    assert _DASHBOARD_COPY.read_bytes() == CATALOG_PATH.read_bytes()
    assert json.loads(_DASHBOARD_COPY.read_text())["contractVersion"] == "external-use-blockers.v1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --locked pytest -q -p no:cacheprovider tests/contract/test_external_use_blockers.py`
Expected: FAIL with `ImportError` (no `external_use_blockers` module, no `PAIR_REASON_REMEDIATIONS`).

- [ ] **Step 3: Write the catalog**

`contracts/catalogs/external-use-blockers.v1.json` with these codes (all reasons from `_remediation` plus the eligible sentinel is not a blocker):

```json
{
  "contractVersion": "external-use-blockers.v1",
  "reasons": {
    "HEIGHT_PRODUCT_DEFINITION_UNRESOLVED": {"title": "높이 산출 기준이 아직 정의되지 않았습니다", "explanation": "높이 값을 어떤 기준면에서 어떻게 읽을지 제품 정의가 확정되지 않아 판정을 열지 않습니다.", "owner": "ADMIN", "target": "HEIGHT"},
    "SUBJECT_NOT_SEALED": {"title": "산출물 파일이 아직 봉인되지 않았습니다", "explanation": "등록만 된 파일은 바이트가 확정되지 않아 어떤 용도 판정도 시작할 수 없습니다.", "owner": "CUSTOMER", "target": "SUBJECT"},
    "POLICY_UNAVAILABLE": {"title": "이 산출물에 적용할 검사 기준이 없습니다", "explanation": "요청한 용도와 산출물 조합을 허용하는 활성 검사 기준(정책)이 등록되어 있지 않습니다.", "owner": "ADMIN", "target": "POLICY"},
    "INSPECTION_REPORT_BINDING_INVALID": {"title": "파일 검사 결과가 현재 기준과 맞지 않습니다", "explanation": "봉인된 파일에 대한 검사 보고가 없거나 현재 검사 기준과 다른 기준으로 작성되었습니다.", "owner": "OPERATOR", "target": "INSPECTION"},
    "ORTHO_MEASUREMENT_UNAVAILABLE": {"title": "정사영상 측정값이 없습니다", "explanation": "정사영상 파일이 MEASURED로 검사되지 않아 표시 용도를 열 수 없습니다.", "owner": "CUSTOMER", "target": "INSPECTION"},
    "DISPLAY_RECEIPT_BINDING_INVALID": {"title": "표시용 정제본이 아직 준비되지 않았습니다", "explanation": "검사를 통과한 파일의 표시용 정제본 영수증이 없거나 현재 보고와 맞지 않습니다.", "owner": "OPERATOR", "target": "DISPLAY"},
    "VOLUME_AUTHORITY_UNAVAILABLE": {"title": "체적 비교 매핑이 없습니다", "explanation": "두 시점을 같은 구역·기준으로 비교해도 된다는 호환성 매핑이 등록되어 있지 않거나 만료되었습니다.", "owner": "ADMIN", "target": "MAPPING"},
    "COMPATIBILITY_MAPPING_MISSING": {"title": "호환성 매핑이 등록되지 않았습니다", "explanation": "이 시점 쌍에 대한 호환성 매핑 기록이 없습니다.", "owner": "ADMIN", "target": "MAPPING"},
    "VOLUME_ZONE_BINDING_INVALID": {"title": "체적 구역 선택이 올바르지 않습니다", "explanation": "선택한 구역이 활성 구역이 아니거나 매핑에 묶인 구역 정의와 다릅니다.", "owner": "OPERATOR", "target": "ZONE"},
    "EVIDENCE_RECORD_BINDING_INVALID": {"title": "검증된 체크포인트 증거가 없습니다", "explanation": "두 시점 각각에 대해 Core가 검증한 체크포인트 증거 기록이 현재 기준으로 존재해야 합니다.", "owner": "CUSTOMER", "target": "EVIDENCE"},
    "EVIDENCE_INDEPENDENCE_UNATTESTED": {"title": "체크포인트 증거에 독립성 확인이 없습니다", "explanation": "증거는 검증됐지만, 재구성과 독립적으로 측정했다는 별도 확인이 증거 컨텍스트에 없습니다. 상대 체적 판정은 시점마다 이 확인을 요구합니다.", "owner": "ADMIN", "target": "EVIDENCE"},
    "PAIR_SUBJECTS_NOT_DISTINCT": {"title": "같은 산출물끼리는 비교할 수 없습니다", "explanation": "기준 시점과 현재 시점으로 같은 산출물 개정을 선택했습니다.", "owner": "OPERATOR", "target": "SUBJECT"}
  },
  "remediations": {
    "DEFINE_HEIGHT_PRODUCT": {"step": "높이 산출 기준이 제품에 정의될 때까지 이 용도는 사용할 수 없습니다.", "owner": "ADMIN", "target": "HEIGHT"},
    "SEAL_EXTERNAL_RECONSTRUCTION": {"step": "등록한 산출물의 업로드를 마치고 봉인하세요.", "owner": "CUSTOMER", "target": "SUBJECT"},
    "AUTHORIZE_POLICY": {"step": "관리자에게 이 산출물 쌍과 용도를 허용하는 검사 기준 등록을 요청하세요.", "owner": "ADMIN", "target": "POLICY"},
    "COMPLETE_CURRENT_INSPECTION": {"step": "현재 검사 기준으로 파일 검사가 끝날 때까지 기다리거나 상태를 새로고침하세요.", "owner": "OPERATOR", "target": "INSPECTION"},
    "MEASURE_DECLARED_ORTHO": {"step": "지원 형식의 정사영상을 다시 등록해 검사를 통과시키세요.", "owner": "CUSTOMER", "target": "INSPECTION"},
    "SEAL_SANITIZED_DISPLAY": {"step": "표시용 정제본 준비가 끝날 때까지 기다리거나 상태를 새로고침하세요.", "owner": "OPERATOR", "target": "DISPLAY"},
    "AUTHORIZE_VOLUME_ZONE_AND_MAPPING": {"step": "관리자에게 이 시점 쌍과 구역에 대한 호환성 매핑 등록을 요청하세요.", "owner": "ADMIN", "target": "MAPPING"},
    "AUTHORIZE_COMPATIBILITY_MAPPING": {"step": "관리자에게 호환성 매핑 등록을 요청하세요.", "owner": "ADMIN", "target": "MAPPING"},
    "SELECT_ACTIVE_VOLUME_ZONE": {"step": "현장의 활성 구역 중 하나를 선택해 다시 요청하세요.", "owner": "OPERATOR", "target": "ZONE"},
    "VALIDATE_INDEPENDENT_EVIDENCE": {"step": "두 시점 모두에 체크포인트 CSV 증거를 등록·봉인하고 검증이 끝날 때까지 기다리세요.", "owner": "CUSTOMER", "target": "EVIDENCE"},
    "ATTEST_INDEPENDENT_EVIDENCE": {"step": "관리자에게 독립 측량 확인이 담긴 증거 컨텍스트 등록을 요청한 뒤 증거 검증과 매핑을 다시 진행하세요.", "owner": "ADMIN", "target": "EVIDENCE"},
    "SELECT_DISTINCT_EPOCHS": {"step": "서로 다른 촬영 시점의 산출물을 기준과 현재로 선택하세요.", "owner": "OPERATOR", "target": "SUBJECT"},
    "RESOLVE_EXTERNAL_USE_BLOCKER": {"step": "전문가 정보의 사유 코드를 확인하고 운영자에게 문의하세요.", "owner": "OPERATOR", "target": "GENERAL"}
  }
}
```

- [ ] **Step 4: Expose the remediation map and add the loader**

In the evaluator, replace the dict literal inside `_remediation` with a module constant defined near the top of the module (after `_MAX_...` constants or before the class):

```python
PAIR_REASON_REMEDIATIONS: dict[str, str] = {
    "HEIGHT_PRODUCT_DEFINITION_UNRESOLVED": "DEFINE_HEIGHT_PRODUCT",
    "SUBJECT_NOT_SEALED": "SEAL_EXTERNAL_RECONSTRUCTION",
    "POLICY_UNAVAILABLE": "AUTHORIZE_POLICY",
    "INSPECTION_REPORT_BINDING_INVALID": "COMPLETE_CURRENT_INSPECTION",
    "ORTHO_MEASUREMENT_UNAVAILABLE": "MEASURE_DECLARED_ORTHO",
    "DISPLAY_RECEIPT_BINDING_INVALID": "SEAL_SANITIZED_DISPLAY",
    "VOLUME_AUTHORITY_UNAVAILABLE": "AUTHORIZE_VOLUME_ZONE_AND_MAPPING",
    "COMPATIBILITY_MAPPING_MISSING": "AUTHORIZE_COMPATIBILITY_MAPPING",
    "VOLUME_ZONE_BINDING_INVALID": "SELECT_ACTIVE_VOLUME_ZONE",
    "EVIDENCE_RECORD_BINDING_INVALID": "VALIDATE_INDEPENDENT_EVIDENCE",
    "EVIDENCE_INDEPENDENCE_UNATTESTED": "ATTEST_INDEPENDENT_EVIDENCE",
    "PAIR_SUBJECTS_NOT_DISTINCT": "SELECT_DISTINCT_EPOCHS",
}
```

and `_remediation` becomes `return PAIR_REASON_REMEDIATIONS.get(reason, "RESOLVE_EXTERNAL_USE_BLOCKER")` after the `None` check.

`external_use_blockers.py`:

```python
"""Loader for the external-use blocker catalog (contracts/catalogs/external-use-blockers.v1.json)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CATALOG_PATH = (
    Path(__file__).resolve().parents[6] / "contracts" / "catalogs" / "external-use-blockers.v1.json"
)

Owner = Literal["OPERATOR", "ADMIN", "CUSTOMER"]
Target = Literal[
    "SUBJECT", "INSPECTION", "DISPLAY", "POLICY", "EVIDENCE", "MAPPING", "ZONE", "HEIGHT", "GENERAL"
]


class BlockerReason(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=500)
    owner: Owner
    target: Target


class BlockerRemediation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    step: str = Field(min_length=1, max_length=300)
    owner: Owner
    target: Target


class ExternalUseBlockerCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)
    contract_version: Literal["external-use-blockers.v1"] = Field(alias="contractVersion")
    reasons: dict[str, BlockerReason]
    remediations: dict[str, BlockerRemediation]


@lru_cache(maxsize=1)
def load_external_use_blocker_catalog() -> ExternalUseBlockerCatalog:
    return ExternalUseBlockerCatalog.model_validate(json.loads(CATALOG_PATH.read_text("utf-8")))


__all__ = ["CATALOG_PATH", "ExternalUseBlockerCatalog", "load_external_use_blocker_catalog"]
```

Check `parents[6]` resolves to the repo root from `services/core/src/ksi_core/domains/external/quantity/` (quantity=0 … repo=6) with `python -c`.

- [ ] **Step 5: Run the test (sync test still fails until Task 2)**

Run: `uv run --locked pytest -q -p no:cacheprovider tests/contract/test_external_use_blockers.py`
Expected: first two PASS, `test_dashboard_copy_is_byte_identical_to_the_contract` FAIL (file missing).

- [ ] **Step 6: Commit**

```bash
git add contracts/catalogs/external-use-blockers.v1.json services/core/src/ksi_core/domains/external/quantity/external_use_blockers.py services/core/src/ksi_core/domains/external/quantity/external_use_evaluator.py tests/contract/test_external_use_blockers.py
git commit -m "feat(contracts): explain external-use blocker codes in a versioned catalog"
```

---

### Task 2: Dashboard catalog sync and lookup helper

**Files:**
- Create: `tools/sync_external_use_blockers.py`
- Create: `apps/dashboard/src/lib/external-use-blockers.generated.json` (by running the tool)
- Create: `apps/dashboard/src/lib/external-use-blockers.ts`
- Test: `apps/dashboard/test/external-use-blockers.test.ts`

**Interfaces:**
- Produces: `explainExternalUseDecision(reasons: readonly string[], remediations: readonly string[]): ExternalUseBlockerGuide` where `ExternalUseBlockerGuide = { known: boolean; title: string; explanation: string; step: string; owner: "OPERATOR"|"ADMIN"|"CUSTOMER"; ownerLabel: string; target: BlockerTarget; codes: string[] }`, `BLOCKER_TARGET_ANCHOR: Record<BlockerTarget, string>`.

- [ ] **Step 1: Write the failing vitest**

```ts
import { describe, expect, it } from "vitest";

import { explainExternalUseDecision } from "@/lib/external-use-blockers";

describe("explainExternalUseDecision", () => {
  it("explains a known reason and its remediation in Korean", () => {
    const guide = explainExternalUseDecision(["EVIDENCE_INDEPENDENCE_UNATTESTED"], ["ATTEST_INDEPENDENT_EVIDENCE"]);
    expect(guide.known).toBe(true);
    expect(guide.title).toBe("체크포인트 증거에 독립성 확인이 없습니다");
    expect(guide.step).toContain("독립 측량 확인");
    expect(guide.owner).toBe("ADMIN");
    expect(guide.ownerLabel).toBe("관리자");
    expect(guide.target).toBe("EVIDENCE");
    expect(guide.codes).toEqual(["EVIDENCE_INDEPENDENCE_UNATTESTED", "ATTEST_INDEPENDENT_EVIDENCE"]);
  });

  it("falls back without crashing on an unknown code and keeps the raw codes", () => {
    const guide = explainExternalUseDecision(["SOMETHING_NEW"], []);
    expect(guide.known).toBe(false);
    expect(guide.title).toBe("판정이 막혔습니다");
    expect(guide.step).toContain("운영자");
    expect(guide.codes).toEqual(["SOMETHING_NEW"]);
  });

  it("uses the first reason when several are reported", () => {
    const guide = explainExternalUseDecision(["POLICY_UNAVAILABLE", "SUBJECT_NOT_SEALED"], ["AUTHORIZE_POLICY"]);
    expect(guide.target).toBe("POLICY");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run (from `apps/dashboard/`): `npm test -- test/external-use-blockers.test.ts`
Expected: FAIL, module not found.

- [ ] **Step 3: Write the sync tool, run it, write the helper**

`tools/sync_external_use_blockers.py`:

```python
"""Copy the external-use blocker catalog into the dashboard (byte-identical)."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "contracts" / "catalogs" / "external-use-blockers.v1.json"
TARGET = ROOT / "apps" / "dashboard" / "src" / "lib" / "external-use-blockers.generated.json"


def main() -> None:
    shutil.copyfile(SOURCE, TARGET)
    print(f"synced {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
```

Run: `uv run --locked python tools/sync_external_use_blockers.py`.

`apps/dashboard/src/lib/external-use-blockers.ts`:

```ts
import catalog from "./external-use-blockers.generated.json";

export type BlockerOwner = "OPERATOR" | "ADMIN" | "CUSTOMER";
export type BlockerTarget =
  | "SUBJECT" | "INSPECTION" | "DISPLAY" | "POLICY" | "EVIDENCE" | "MAPPING" | "ZONE" | "HEIGHT" | "GENERAL";

type Reason = { title: string; explanation: string; owner: BlockerOwner; target: BlockerTarget };
type Remediation = { step: string; owner: BlockerOwner; target: BlockerTarget };

const REASONS = catalog.reasons as Record<string, Reason>;
const REMEDIATIONS = catalog.remediations as Record<string, Remediation>;

export const BLOCKER_OWNER_LABEL: Record<BlockerOwner, string> = {
  OPERATOR: "운영자",
  ADMIN: "관리자",
  CUSTOMER: "고객(산출물 제공자)",
};

/** Anchor ids rendered by the external panels; unknown targets fall back to GENERAL. */
export const BLOCKER_TARGET_ANCHOR: Record<BlockerTarget, string> = {
  SUBJECT: "external-submissions",
  INSPECTION: "external-inspection",
  DISPLAY: "external-display",
  POLICY: "external-inspection",
  EVIDENCE: "external-evidence",
  MAPPING: "external-volume",
  ZONE: "external-volume",
  HEIGHT: "external-inspection",
  GENERAL: "external-submissions",
};

export type ExternalUseBlockerGuide = {
  known: boolean;
  title: string;
  explanation: string;
  step: string;
  owner: BlockerOwner;
  ownerLabel: string;
  target: BlockerTarget;
  codes: string[];
};

const FALLBACK_STEP = "전문가 정보의 사유 코드를 확인하고 운영자에게 문의하세요.";

export function explainExternalUseDecision(
  reasons: readonly string[],
  remediations: readonly string[],
): ExternalUseBlockerGuide {
  const reason = reasons.map((code) => REASONS[code]).find((item) => item !== undefined);
  const remediation = remediations.map((code) => REMEDIATIONS[code]).find((item) => item !== undefined);
  const codes = [...reasons, ...remediations];
  if (!reason) {
    return {
      known: false,
      title: "판정이 막혔습니다",
      explanation: "이 사유는 아직 안내 목록에 없습니다. 사유 코드는 전문가 정보에서 확인할 수 있습니다.",
      step: remediation?.step ?? FALLBACK_STEP,
      owner: remediation?.owner ?? "OPERATOR",
      ownerLabel: BLOCKER_OWNER_LABEL[remediation?.owner ?? "OPERATOR"],
      target: remediation?.target ?? "GENERAL",
      codes,
    };
  }
  const owner = remediation?.owner ?? reason.owner;
  return {
    known: true,
    title: reason.title,
    explanation: reason.explanation,
    step: remediation?.step ?? FALLBACK_STEP,
    owner,
    ownerLabel: BLOCKER_OWNER_LABEL[owner],
    target: reason.target,
    codes,
  };
}
```

- [ ] **Step 4: Run both test suites**

Run: `npm test -- test/external-use-blockers.test.ts` (PASS) and `uv run --locked pytest -q -p no:cacheprovider tests/contract/test_external_use_blockers.py` (all PASS).

- [ ] **Step 5: Commit**

```bash
git add tools/sync_external_use_blockers.py apps/dashboard/src/lib/external-use-blockers.generated.json apps/dashboard/src/lib/external-use-blockers.ts apps/dashboard/test/external-use-blockers.test.ts
git commit -m "feat(dashboard): explain external-use blockers from the synced catalog"
```

---

### Task 3: Blocker card in the external panels

**Files:**
- Create: `apps/dashboard/src/components/external-results/ExternalUseBlockerCard.tsx`
- Modify: `apps/dashboard/src/app/field/ExternalResultWorkflowPanel.tsx` (BLOCKED branch, around line 736)
- Modify: `apps/dashboard/src/app/field/ExternalEvidencePanel.tsx` (`DecisionReceipt`, around line 184)
- Test: `apps/dashboard/test/external-use-blocker-card.test.tsx`

**Interfaces:**
- Consumes: `explainExternalUseDecision`, `BLOCKER_TARGET_ANCHOR` from Task 2.
- Produces: `<ExternalUseBlockerCard reasons remediations intro? />`.

- [ ] **Step 1: Write the failing test**

```tsx
// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { ExternalUseBlockerCard } from "@/components/external-results/ExternalUseBlockerCard";

afterEach(cleanup);

it("renders why, what to do, owner and a link to the target panel", () => {
  render(<ExternalUseBlockerCard reasons={["EVIDENCE_INDEPENDENCE_UNATTESTED"]} remediations={["ATTEST_INDEPENDENT_EVIDENCE"]} />);
  expect(screen.getByRole("alert")).toHaveTextContent("체크포인트 증거에 독립성 확인이 없습니다");
  expect(screen.getByText("지금 할 일")).toBeInTheDocument();
  expect(screen.getByText(/독립 측량 확인/)).toBeInTheDocument();
  expect(screen.getByText("담당: 관리자")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "관련 화면으로 이동" })).toHaveAttribute("href", "#external-evidence");
  expect(screen.getByText("EVIDENCE_INDEPENDENCE_UNATTESTED, ATTEST_INDEPENDENT_EVIDENCE")).toBeInTheDocument();
});

it("keeps raw codes visible for unknown reasons", () => {
  render(<ExternalUseBlockerCard reasons={["NEW_CODE"]} remediations={[]} />);
  expect(screen.getByRole("alert")).toHaveTextContent("판정이 막혔습니다");
  expect(screen.getByText("NEW_CODE")).toBeInTheDocument();
});
```

Check that `@testing-library/jest-dom` matchers are configured (look at `apps/dashboard/test/setup.ts` or existing tests using `toHaveTextContent`); if not, use `.textContent` assertions instead.

- [ ] **Step 2: Run to verify it fails**

Run: `npm test -- test/external-use-blocker-card.test.tsx` → FAIL (component missing).

- [ ] **Step 3: Write the component and wire it**

```tsx
import { BLOCKER_TARGET_ANCHOR, explainExternalUseDecision } from "@/lib/external-use-blockers";

export function ExternalUseBlockerCard({
  reasons,
  remediations,
  intro,
}: {
  reasons: readonly string[];
  remediations: readonly string[];
  intro?: string;
}) {
  const guide = explainExternalUseDecision(reasons, remediations);
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-lg border border-high/30 bg-high-bg p-3 text-[13px] text-high-ink">
      {intro && <p className="text-ink-2">{intro}</p>}
      <p className="text-[14px] font-bold break-keep">{guide.title}</p>
      <p className="break-keep">{guide.explanation}</p>
      <div className="rounded-md bg-surface/70 px-3 py-2">
        <p className="text-[11.5px] font-bold text-ink-muted">지금 할 일</p>
        <p className="mt-1 break-keep">{guide.step}</p>
        <p className="mt-1 text-[12px] text-ink-2">담당: {guide.ownerLabel}</p>
      </div>
      <a className="w-fit text-[12.5px] font-semibold underline" href={`#${BLOCKER_TARGET_ANCHOR[guide.target]}`}>
        관련 화면으로 이동
      </a>
      <details className="text-[12px] text-ink-2">
        <summary>전문가 정보</summary>
        <p className="mt-1 font-mono">{guide.codes.join(", ")}</p>
      </details>
    </div>
  );
}
```

In `ExternalResultWorkflowPanel.tsx`, replace the BLOCKED branch body:

```tsx
) : decision.verdict !== "ELIGIBLE" ? (
  <ExternalUseBlockerCard
    reasons={decision.reasons}
    remediations={decision.remediations}
    intro="현재 선택으로는 상대 물량 비교를 요청할 수 없습니다."
  />
) : canIssue ? (
```

In `ExternalEvidencePanel.tsx` `DecisionReceipt`, render the card when `decision.verdict === "BLOCKED"` and keep the existing lines for other verdicts:

```tsx
{decision.verdict === "BLOCKED" ? (
  <ExternalUseBlockerCard reasons={decision.reasons} remediations={decision.remediations} />
) : (
  <>
    <p>사유: {decision.reasons.join(", ") || "없음"}</p>
    <p>조치: {decision.remediations.join(", ") || "없음"}</p>
  </>
)}
```

Add `id="external-evidence"`, `id="external-volume"`, `id="external-submissions"`, `id="external-inspection"`, `id="external-display"` to the corresponding `<section>` roots in the panels if they do not already have ids (grep `id=` first).

- [ ] **Step 4: Run tests**

Run: `npm test -- test/external-use-blocker-card.test.tsx test/external-result-workflow-panel.test.tsx test/external-evidence-panel-correction.test.tsx` → PASS. If an existing test asserted the old `사유:` text for BLOCKED, update its expectation to the new title.

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/src/components/external-results/ExternalUseBlockerCard.tsx apps/dashboard/src/app/field/ExternalResultWorkflowPanel.tsx apps/dashboard/src/app/field/ExternalEvidencePanel.tsx apps/dashboard/test/external-use-blocker-card.test.tsx
git commit -m "feat(dashboard): show why a decision is blocked and what to do next"
```

---

### Task 4: External work-order stage derivation and next-action consistency

**Files:**
- Create: `apps/dashboard/src/app/field/external-work-order-stage.ts`
- Modify: `apps/dashboard/src/app/field/work-orders/[workOrderId]/page.tsx` (data loading around line 68, `cardPresentation` around line 120)
- Test: `apps/dashboard/test/external-work-order-stage.test.ts`

**Interfaces:**
- Produces: `deriveExternalWorkOrderStage(input: ExternalStageInput): ExternalStagePresentation` where
  `ExternalStageInput = { planningOnly: boolean; workflowClosed: boolean; sealedSubmissionCount: number; registeredSubmissionCount: number; latestResult: ExternalResultSummaryView | null }` and
  `ExternalStagePresentation = { stage: "CLOSED"|"REGISTER"|"SEAL"|"DECIDE"|"REVIEW"|"PROPOSE"|"DONE"; label: string; detail: string; tone: Tone; anchor: string }`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";

import { deriveExternalWorkOrderStage } from "@/app/field/external-work-order-stage";
import type { ExternalResultSummaryView } from "@/lib/core-api/types";

const base = { planningOnly: false, workflowClosed: false, sealedSubmissionCount: 0, registeredSubmissionCount: 0, latestResult: null };

function result(overrides: Partial<ExternalResultSummaryView> = {}): ExternalResultSummaryView {
  return {
    reportRef: "report-1", reportDigest: "sha256:a", requestRef: "req-1", requestDigest: "sha256:b",
    sourceWorkOrderId: "wo-1", currentWorkOrderId: "wo-1", baselineWorkOrderId: "wo-0",
    decisionId: "d-1", decisionDigest: "sha256:c", workAreaId: "area-1", zoneDefinitionDigest: "sha256:d",
    crs: "EPSG:5186", observedCrsDigest: "sha256:e", verticalReferenceDigest: "sha256:f",
    baselineCapturedFrom: "2026-09-01T00:00:00Z", baselineCapturedTo: "2026-09-01T01:00:00Z",
    currentCapturedFrom: "2026-09-02T00:00:00Z", currentCapturedTo: "2026-09-02T01:00:00Z",
    reportedAt: "2026-09-02T02:00:00Z", measurementStatus: "SUCCEEDED", measurementReason: null,
    metrics: null, executionPolicy: { policyId: "p", version: 1, policyDigest: "sha256:g", algorithmBuildDigest: "sha256:h", configDigest: "sha256:i", uncertaintyMethod: "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1" },
    reviewRef: null, reviewDigest: null, reviewedAt: null, proposalCount: 0, approvedProposalCount: 0,
    ...overrides,
  } as ExternalResultSummaryView;
}

describe("deriveExternalWorkOrderStage", () => {
  it("asks for registration when nothing is registered", () => {
    expect(deriveExternalWorkOrderStage(base)).toMatchObject({ stage: "REGISTER", label: "외부 산출물 등록 준비" });
  });
  it("asks to seal when a registration is not sealed", () => {
    expect(deriveExternalWorkOrderStage({ ...base, registeredSubmissionCount: 1 })).toMatchObject({ stage: "SEAL", label: "업로드와 봉인 완료" });
  });
  it("asks for a comparison decision when sealed but no result", () => {
    expect(deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1 })).toMatchObject({ stage: "DECIDE", label: "검사와 비교 판정" });
  });
  it("asks for review when a result exists without review", () => {
    expect(deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1, latestResult: result() })).toMatchObject({ stage: "REVIEW", label: "결과와 근거 검토" });
  });
  it("asks for a proposal decision after review", () => {
    expect(deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1, latestResult: result({ reviewRef: "err-1", reviewedAt: "2026-09-02T03:00:00Z" }) })).toMatchObject({ stage: "PROPOSE", label: "재관측 필요 여부 결정" });
  });
  it("is done after an approved proposal", () => {
    expect(deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1, latestResult: result({ reviewRef: "err-1", approvedProposalCount: 1 }) })).toMatchObject({ stage: "DONE", label: "후속 관측 계획됨" });
  });
  it("closed wins over everything", () => {
    expect(deriveExternalWorkOrderStage({ ...base, workflowClosed: true, latestResult: result() }).stage).toBe("CLOSED");
  });
  it("labels planning-only successors for registration", () => {
    expect(deriveExternalWorkOrderStage({ ...base, planningOnly: true })).toMatchObject({ stage: "REGISTER", label: "승인된 재관측 산출물 등록" });
  });
  it("ignores a result that belongs to another work order", () => {
    expect(deriveExternalWorkOrderStage({ ...base, sealedSubmissionCount: 1, latestResult: result({ currentWorkOrderId: "other" }) }).stage).toBe("DECIDE");
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `npm test -- test/external-work-order-stage.test.ts` → FAIL.

- [ ] **Step 3: Implement**

```ts
import type { ExternalResultSummaryView } from "@/lib/core-api/types";
import type { Tone } from "@/lib/core-api/labels";

export type ExternalStage = "CLOSED" | "REGISTER" | "SEAL" | "DECIDE" | "REVIEW" | "PROPOSE" | "DONE";

export type ExternalStageInput = {
  planningOnly: boolean;
  workflowClosed: boolean;
  sealedSubmissionCount: number;
  registeredSubmissionCount: number;
  latestResult: ExternalResultSummaryView | null;
};

export type ExternalStagePresentation = {
  stage: ExternalStage;
  label: string;
  detail: string;
  tone: Tone;
  anchor: string;
};

/**
 * Derives the operator's next action for an external-reconstruction work order
 * from retained facts only. It never infers processing, flight or device state.
 */
export function deriveExternalWorkOrderStage(input: ExternalStageInput): ExternalStagePresentation {
  if (input.workflowClosed) {
    return { stage: "CLOSED", label: "업무 종료", detail: "이 작업은 종료되었습니다. 새 산출물 등록과 비교·검토 요청은 시작할 수 없으며, 이미 등록한 파일과 결과는 계속 확인할 수 있습니다.", tone: "neutral", anchor: "external-submissions" };
  }
  const result = input.latestResult && input.latestResult.currentWorkOrderId ? input.latestResult : null;
  const ownResult = result && input.latestResult?.currentWorkOrderId === (input as { workOrderId?: string }).workOrderId ? result : null;
  void ownResult;
  return stageFor(input);
}

function stageFor(input: ExternalStageInput): ExternalStagePresentation {
  const own = input.latestResult;
  if (own && own.approvedProposalCount > 0) {
    return { stage: "DONE", label: "후속 관측 계획됨", detail: "검토와 재관측 승인이 끝났습니다. 승인된 후속 작업에서 다음 산출물을 등록합니다.", tone: "positive", anchor: "external-volume" };
  }
  if (own && own.reviewRef) {
    return { stage: "PROPOSE", label: "재관측 필요 여부 결정", detail: "결과 검토가 기록되었습니다. 부족한 구역이 있으면 재관측 제안을 만들고 승인하세요.", tone: "warning", anchor: "external-volume" };
  }
  if (own) {
    return { stage: "REVIEW", label: "결과와 근거 검토", detail: "상대 물량 결과가 준비되었습니다. 수치·범위·불확도를 확인하고 검토를 기록하세요.", tone: "warning", anchor: "external-volume" };
  }
  if (input.sealedSubmissionCount > 0) {
    return { stage: "DECIDE", label: "검사와 비교 판정", detail: "봉인된 산출물의 검사 결과를 확인하고 기준 시점과의 비교 판정을 요청하세요.", tone: "progress", anchor: "external-inspection" };
  }
  if (input.registeredSubmissionCount > 0) {
    return { stage: "SEAL", label: "업로드와 봉인 완료", detail: "등록한 산출물의 파일 업로드를 마치고 봉인해야 검사가 시작됩니다.", tone: "progress", anchor: "external-submissions" };
  }
  return input.planningOnly
    ? { stage: "REGISTER", label: "승인된 재관측 산출물 등록", detail: "승인된 재관측에 필요한 산출물을 등록하세요. 이 작업에서는 비행이나 장비를 실행하지 않습니다.", tone: "progress", anchor: "external-submissions" }
    : { stage: "REGISTER", label: "외부 산출물 등록 준비", detail: "촬영 시각과 재구성 정보를 확인한 뒤 산출물을 등록하세요. 비행이나 장비 실행은 이 작업에서 시작하지 않습니다.", tone: "progress", anchor: "external-submissions" };
}
```

Simplify: the "belongs to another work order" case is handled by the caller passing `latestResult: null` when `currentWorkOrderId !== workOrderId`; delete the `ownResult` lines and make the test pass `latestResult` only for the own order — adjust the last test to pass `null` (the page does the filtering). Keep the function free of `workOrderId`.

In `page.tsx`: for external orders (`externalWorkflow`), load `listExternalReconstructionSubmissions(workOrder.workOrderId)` and `getSiteWorkspace(workOrder.siteId)` unconditionally (they are already imported), then:

```ts
const externalStage = externalWorkflow
  ? deriveExternalWorkOrderStage({
      planningOnly,
      workflowClosed,
      sealedSubmissionCount: submissions.filter((item) => item.state === "SEALED").length,
      registeredSubmissionCount: submissions.filter((item) => item.state === "REGISTERED").length,
      latestResult:
        workspace?.externalResult.state === "AVAILABLE" &&
        workspace.externalResult.result?.currentWorkOrderId === workOrder.workOrderId
          ? workspace.externalResult.result
          : null,
    })
  : null;
const cardPresentation = externalStage
  ? { label: externalStage.label, detail: externalStage.detail, tone: externalStage.tone }
  : externalExecutionContext === "UNVERIFIED" ? { …existing… } : presentation;
```

Remove the now-redundant `workflowClosed` / `planningOnly` / `externalIngress` branches of `cardPresentation`. Keep the informational paragraphs below the card unchanged.

- [ ] **Step 4: Run tests and typecheck** — `npm test -- test/external-work-order-stage.test.ts test/work-order-stage.test.ts` and `npx tsc --noEmit` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/src/app/field/external-work-order-stage.ts apps/dashboard/src/app/field/work-orders/[workOrderId]/page.tsx apps/dashboard/test/external-work-order-stage.test.ts
git commit -m "feat(dashboard): derive the external work-order next action from retained loop facts"
```

---

### Task 5: Post-commit listeners on the volume store, review store and proposal service

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_relative_volumes.py` (`__init__` ~851, `record_observed_report` ~2010-2125)
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_result_reviews.py` (`__init__` ~139, `review` ~240-294)
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_reobservation_proposals.py` (`ExternalReobservationProposalService` ~773-900)
- Test: `tests/contract/test_external_result_listeners.py`

**Interfaces:**
- Produces: `ExternalRelativeVolumeStore.bind_report_listener(listener: Callable[[ExternalRelativeVolumeRecord], None])`, `ExternalResultReviewStore.bind_review_listener(listener: Callable[[ExternalResultReviewReceiptV1], None])`, `ExternalReobservationProposalService.bind_approval_listener(listener: Callable[[ExternalReobservationApprovalReceiptV1], None])`. Listeners run after the journal append, outside store locks and coordinator guards; exceptions are logged, never raised; retries/idempotent replays do not notify.

- [ ] **Step 1: Write the failing test**

```python
"""Post-commit listeners fire once per new report/review/approval and never break the mutation."""

from __future__ import annotations

from pathlib import Path

from external_product_loop_fixture import build_graph, record_measurement, seed_original
from test_external_result_review_proposals import _NOW, _principal


def test_report_review_and_approval_listeners_fire_once_and_isolate_failures(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    reports: list[str] = []
    reviews: list[str] = []
    approvals: list[str] = []

    def failing(_record: object) -> None:
        raise RuntimeError("projection failed")

    graph.volumes.bind_report_listener(failing)
    graph.volumes.bind_report_listener(lambda record: reports.append(record.report.report_id))
    graph.service.reviews.bind_review_listener(lambda receipt: reviews.append(receipt.review_ref))
    graph.service.bind_approval_listener(lambda receipt: approvals.append(receipt.successor_work_order_id))

    report = record_measurement(graph)
    assert reports == [report.report_id]

    receipt = graph.service.reviews.review(
        organization_id="org-a", report_ref=report.report_id, principal=_principal(), evaluated_at=_NOW
    )
    again = graph.service.reviews.review(
        organization_id="org-a", report_ref=report.report_id, principal=_principal(), evaluated_at=_NOW
    )
    assert again == receipt and reviews == [receipt.review_ref]

    created = graph.service.create_proposal(...)  # see Step 3 for the exact call
    approved = graph.service.approve(
        organization_id="org-a", proposal_ref=created.proposal_ref, expected_version=1,
        principal=_principal(), actor=_principal().principal_id, now=_NOW, idempotency_key="approve-1",
    )
    retry = graph.service.approve(
        organization_id="org-a", proposal_ref=created.proposal_ref, expected_version=1,
        principal=_principal(), actor=_principal().principal_id, now=_NOW, idempotency_key="approve-1",
    )
    assert retry.successor_work_order_id == approved.successor_work_order_id
    assert approvals == [approved.successor_work_order_id]
    graph.close()
```

Before writing, read `tests/contract/test_external_result_review_proposals.py` for the exact `create_proposal` call (arguments `organization_id`, `report_ref`, `target_work_area_ids`, `principal`, `now`, `idempotency_key`, `reason`) and the `_principal()` helper name, and use them verbatim.

- [ ] **Step 2: Run to verify it fails** — `uv run --locked pytest -q -p no:cacheprovider tests/contract/test_external_result_listeners.py` → FAIL (`bind_report_listener` missing).

- [ ] **Step 3: Implement the three listener hooks**

Volume store `__init__` (before `self._replay()`): `self._report_listeners: list[Callable[[ExternalRelativeVolumeRecord], None]] = []`.

Add methods:

```python
    def bind_report_listener(
        self, listener: Callable[[ExternalRelativeVolumeRecord], None]
    ) -> None:
        """Bind a post-commit projection; the report verdict never depends on it."""
        with self._lock:
            if listener not in self._report_listeners:
                self._report_listeners.append(listener)

    def _notify_report_listeners(self, record: ExternalRelativeVolumeRecord) -> None:
        for listener in tuple(self._report_listeners):
            try:
                listener(record)
            except Exception:
                _LOGGER.exception(
                    "relative volume report listener failed",
                    extra={"request_ref": record.request.request_id},
                )
```

(Add `_LOGGER = logging.getLogger(__name__)` if the module has none.) In `record_observed_report`, declare `reported: ExternalRelativeVolumeRecord | None = None` before the `with (self._coordinator.mutation(), …)` block; replace the final `return ExternalRelativeVolumeResult(REPORTED, self._records[request_ref])` inside the block with `reported = self._records[request_ref]`, and after the block:

```python
        assert reported is not None
        self._notify_report_listeners(reported)
        return ExternalRelativeVolumeResult(ExternalRelativeVolumeVerdict.REPORTED, reported)
```

Review store: same pattern with `self._review_listeners`, `bind_review_listener`, `_notify_review_listeners(receipt)`; in `review()` set `recorded = receipt.model_copy(deep=True)` instead of returning inside the `with`, notify after the block, then return `recorded`. The idempotent branch (`existing is not None`) keeps returning inside the block without notifying.

Proposal service (frozen dataclass): add `approval_listeners: list[Callable[[ExternalReobservationApprovalReceiptV1], None]] = field(default_factory=list, compare=False)` and

```python
    def bind_approval_listener(
        self, listener: Callable[[ExternalReobservationApprovalReceiptV1], None]
    ) -> None:
        if listener not in self.approval_listeners:
            self.approval_listeners.append(listener)
```

In `approve`, the fresh path (`with self.authority_port.preflight_approval(...)`) assigns `receipt = self.work_orders.approve_external_reobservation(...)`; after the `with` block notify each listener with try/except + `_LOGGER.exception`, then return `receipt`. The idempotent `existing is not None` path returns without notifying.

- [ ] **Step 4: Run the new test and the existing store tests**

Run: `uv run --locked pytest -q -p no:cacheprovider tests/contract/test_external_result_listeners.py tests/contract/test_external_relative_volumes.py tests/contract/test_external_result_review_proposals.py tests/contract/test_external_result_workflow_api.py` → PASS.

- [ ] **Step 5: Commit**

```bash
git add services/core/src/ksi_core/domains/external/quantity/external_relative_volumes.py services/core/src/ksi_core/domains/external/workflow/external_result_reviews.py services/core/src/ksi_core/domains/external/workflow/external_reobservation_proposals.py tests/contract/test_external_result_listeners.py
git commit -m "feat(core): post-commit listeners for external reports, reviews and approvals"
```

---

### Task 6: Deterministic external result briefing projector

**Files:**
- Create: `services/core/src/ksi_core/domains/external/workflow/external_result_briefings.py`
- Modify: `services/core/src/ksi_core/domains/workspace/site_workspace.py` (`SiteBriefingStore`: add `latest_for_organization`)
- Test: `tests/contract/test_external_result_briefings.py`

**Interfaces:**
- Consumes: `SiteBriefingStore.record(...)` / `.latest(site_id, organization_id=)`, `ExternalResultReadProjector.report_for_site(...)` / `.history_for_site(...)`, `WorkAreaStore.get(id)`, listener types from Task 5.
- Produces: `ExternalResultBriefingProjector(briefings, projector, work_areas, clock=None)` with `on_report(record)`, `on_review(receipt)`, `on_approval(receipt)`, `bind(volumes, reviews, service)`; `SiteBriefingStore.latest_for_organization(organization_id) -> list[SiteBriefing]` newest first.

- [ ] **Step 1: Write the failing test**

```python
"""External result briefings are deterministic, cited, idempotent and never block the mutation."""

from __future__ import annotations

from pathlib import Path

from external_product_loop_fixture import build_graph, record_measurement, seed_original
from ksi_core.domains.external.workflow.external_result_briefings import (
    ExternalResultBriefingProjector,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_result_workflow_api import ExternalResultReadProjector
from ksi_core.site_workspace import SiteBriefingStore
from ksi_event_contracts.copilot import SiteBriefingStatus
from test_external_result_review_proposals import _NOW, _principal


def _projector(tmp_path: Path, graph):
    briefings = SiteBriefingStore(DurableJournal(tmp_path / "site-briefings.jsonl"), site_store=graph.service.sites)
    read = ExternalResultReadProjector(volumes=graph.volumes, workflow=graph.service, clock=lambda: _NOW)
    projector = ExternalResultBriefingProjector(briefings=briefings, projector=read, work_areas=graph.service.work_areas, clock=lambda: _NOW)
    projector.bind(volumes=graph.volumes, reviews=graph.service.reviews, service=graph.service)
    return briefings, projector


def test_report_review_and_approval_each_record_one_cited_briefing(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, _ = _projector(tmp_path, graph)
    report = record_measurement(graph)

    first = briefings.latest("site-a", organization_id="org-a")
    assert first is not None and first.status is SiteBriefingStatus.READY
    assert first.source_watermark == f"external-report:{report.report_digest}:REPORTED"
    assert "4" in first.what_changed  # net 4 m3 from the fixture payload
    assert "첫 결과" in first.why_it_matters
    assert first.decision_prompt == "결과와 근거를 검토하세요."
    assert {c.source_path for c in first.citations} == {
        f"/v1/external-relative-volume-reports/{report.report_id}",
        f"/v1/sites/site-a/observations/{report.report_id}",
    }

    graph.service.reviews.review(organization_id="org-a", report_ref=report.report_id, principal=_principal(), evaluated_at=_NOW)
    reviewed = briefings.latest("site-a", organization_id="org-a")
    assert reviewed is not None and reviewed.source_watermark.endswith(":REVIEWED")
    assert reviewed.decision_prompt == "재관측이 필요하면 제안을 만들고 승인하세요."

    created = graph.service.create_proposal(...)  # same call as Task 5
    approved = graph.service.approve(organization_id="org-a", proposal_ref=created.proposal_ref, expected_version=1, principal=_principal(), actor=_principal().principal_id, now=_NOW, idempotency_key="approve-1")
    done = briefings.latest("site-a", organization_id="org-a")
    assert done is not None and done.source_watermark.endswith(":APPROVED")
    assert approved.successor_work_order_id in done.decision_prompt
    assert len(briefings.latest_for_organization("org-a")) == 1
    assert briefings.latest_for_organization("org-b") == []
    graph.close()


def test_same_watermark_is_not_recorded_twice(tmp_path: Path) -> None:
    source = seed_original(tmp_path)
    graph = build_graph(tmp_path, source)
    briefings, projector = _projector(tmp_path, graph)
    report = record_measurement(graph)
    record = graph.volumes.get(report.request_id, organization_id="org-a")
    assert record is not None
    projector.on_report(record)  # duplicate delivery
    journal = (tmp_path / "site-briefings.jsonl").read_text().strip().splitlines()
    assert len(journal) == 1
    graph.close()
```

- [ ] **Step 2: Run to verify it fails** — FAIL (module missing).

- [ ] **Step 3: Implement**

`SiteBriefingStore.latest_for_organization`:

```python
    def latest_for_organization(self, organization_id: str) -> list[SiteBriefing]:
        with self._lock:
            items = [
                self._briefings[briefing_id]
                for (org, _site), briefing_id in self._latest.items()
                if org == organization_id
            ]
        return sorted(items, key=lambda item: item.generated_at, reverse=True)
```

`external_result_briefings.py`:

```python
"""Deterministic site briefings for external relative-volume results (AX-2).

Copies sealed report values into the existing SiteBriefing record; the only
arithmetic is the delta between two retained net values. No model call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ksi_event_contracts.copilot import CopilotCitation, SiteBriefingStatus

_LOGGER = logging.getLogger(__name__)
_ACTOR = "system:external-result-briefing"


def _m3(value: float) -> str:
    return f"{value:,.1f} m³"


class ExternalResultBriefingProjector:
    def __init__(self, *, briefings: Any, projector: Any, work_areas: Any, clock: Callable[[], datetime] | None = None) -> None:
        self._briefings = briefings
        self._projector = projector
        self._work_areas = work_areas
        self._clock = clock or (lambda: datetime.now(UTC))

    def bind(self, *, volumes: Any, reviews: Any, service: Any) -> None:
        volumes.bind_report_listener(self.on_report)
        reviews.bind_review_listener(self.on_review)
        service.bind_approval_listener(self.on_approval)

    def on_report(self, record: Any) -> None:
        subject = record.request.current.subject
        self._record(subject.organization_id, subject.site_id, record.report.report_id, stage="REPORTED")

    def on_review(self, receipt: Any) -> None:
        self._record(receipt.organization_id, receipt.site_id, receipt.report_ref, stage="REVIEWED")

    def on_approval(self, receipt: Any) -> None:
        proposal = self._projector_workflow().proposals.get_scoped(receipt.proposal_id, organization_id=receipt.organization_id)
        if proposal is None:
            return
        self._record(receipt.organization_id, receipt.site_id, proposal.report_ref, stage="APPROVED", successor=receipt.successor_work_order_id)

    def _projector_workflow(self) -> Any:
        return self._projector._workflow  # noqa: SLF001 -- same domain, read-only access
```

Prefer adding a public `workflow` property on `ExternalResultReadProjector` instead of the private access: `@property def workflow(self): return self._workflow`, and use it.

```python
    def _record(self, organization_id: str, site_id: str, report_ref: str, *, stage: str, successor: str | None = None) -> None:
        try:
            view = self._projector.report_for_site(site_id, report_ref, organization_id=organization_id)
            result = view.result
            if result is None or result.metrics is None:
                return
            watermark = f"external-report:{result.report_digest}:{stage}"
            latest = self._briefings.latest(site_id, organization_id=organization_id)
            if latest is not None and latest.source_watermark == watermark:
                return
            area = self._work_areas.get(result.work_area_id)
            zone = area.name if area is not None else result.work_area_id
            metrics = result.metrics
            what = (
                f"{zone} 구역의 상대 물량 결과: 절토 {_m3(metrics.cut_m3)}, 성토 {_m3(metrics.fill_m3)}, "
                f"순변화 {_m3(metrics.net_m3)} (기준 {result.baseline_captured_from:%Y-%m-%d} → 현재 "
                f"{result.current_captured_from:%Y-%m-%d}, 유효 면적 {metrics.common_valid_fraction * 100:.0f}%)."
            )
            previous = self._previous_net(site_id, organization_id, result)
            if previous is None:
                why = f"이 구역의 첫 결과입니다. 이후 결과와 비교할 기준이 됩니다."
            else:
                delta = metrics.net_m3 - previous
                why = f"직전 결과({_m3(previous)})보다 순변화가 {_m3(abs(delta))} {'늘었습니다' if delta >= 0 else '줄었습니다'}."
            if stage == "REPORTED":
                prompt = "결과와 근거를 검토하세요."
            elif stage == "REVIEWED":
                prompt = "재관측이 필요하면 제안을 만들고 승인하세요."
            else:
                prompt = f"후속 작업 {successor}에 다음 산출물을 등록하세요."
            unc = metrics.uncertainty_note if metrics.uncertainty_m3 is None else f"불확도 ±{_m3(metrics.uncertainty_m3)} · {metrics.uncertainty_note}"
            citations = [
                CopilotCitation(citation_id=f"report:{report_ref}", object_type="external-relative-volume-report", object_id=report_ref, label=f"{zone} 상대 물량 보고서", source_path=f"/v1/external-relative-volume-reports/{report_ref}", captured_from=result.baseline_captured_from.isoformat(), captured_to=result.current_captured_to.isoformat(), uncertainty_summary=unc[:500]),
                CopilotCitation(citation_id=f"site-observation:{report_ref}", object_type="site-observation", object_id=report_ref, label="현장 관측 결과 보기", source_path=f"/v1/sites/{site_id}/observations/{report_ref}"),
            ]
            self._briefings.record(organization_id=organization_id, site_id=site_id, status=SiteBriefingStatus.READY, what_changed=what, why_it_matters=why, decision_prompt=prompt, citations=citations, uncertainty=unc, source_watermark=watermark, missing_data=[], actor=_ACTOR, now=self._clock())
        except Exception:
            _LOGGER.exception("external result briefing failed", extra={"site_id": site_id, "report_ref": report_ref, "stage": stage})

    def _previous_net(self, site_id: str, organization_id: str, current: Any) -> float | None:
        history = self._projector.history_for_site(site_id, organization_id=organization_id, after=None, limit=50)
        candidates = [
            item.result for item in history.items
            if item.result is not None and item.result.metrics is not None
            and item.result.work_area_id == current.work_area_id
            and item.result.report_ref != current.report_ref
            and item.result.reported_at < current.reported_at
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.reported_at).metrics.net_m3
```

Confirm `ExternalResultSummaryView` field names by reading `external_result_projection_models.py` (`baseline_captured_from`, `current_captured_from`, `reported_at`, `metrics.cut_m3`, …).

- [ ] **Step 4: Run tests** — new test + `tests/contract/test_copilot_conversations.py` (briefing store) → PASS. Run `uv run --locked ruff check` and `mypy` on the new module.

- [ ] **Step 5: Commit**

```bash
git add services/core/src/ksi_core/domains/external/workflow/external_result_briefings.py services/core/src/ksi_core/domains/workspace/site_workspace.py services/core/src/ksi_core/domains/external/workflow/external_result_workflow_api.py tests/contract/test_external_result_briefings.py
git commit -m "feat(core): record deterministic site briefings for external results"
```

---

### Task 7: Wire the briefing store without the copilot and expose latest-per-site

**Files:**
- Modify: `services/core/src/ksi_core/domains/workspace/site_workspace.py` (`build_site_workspace_router`, `mount_site_workspace`)
- Modify: `services/core/src/ksi_core/composition/workspace_graph.py`, `assembly.py`, `assembly_validation.py`, `routes/operations.py`, `app_factory.py`
- Modify: `contracts/api/openapi-core.yaml`
- Modify: `tests/contract/test_api_contract_sync.py` (fixture passes `briefing_store`)
- Test: `tests/contract/test_site_briefing_routes.py`

**Interfaces:**
- `build_site_workspace_router(projector, briefing_service, *, briefing_store)`; `mount_site_workspace(app, *, projector, briefing_service, briefing_store)`; `WorkspaceGraph.site_briefing_store`; `create_app(..., site_briefing_store=None)`.
- Routes: `GET /v1/sites/{site_id}/briefings/latest` (store), `POST /v1/sites/{site_id}/briefings/refresh` (service only), `GET /v1/site-briefings/latest?limit=` → `{"items": [SiteBriefing...]}` (store, `SITES_READ`).

- [ ] **Step 1: Write the failing test** (build a minimal FastAPI app with `mount_auth`, a `SiteStore` with two organizations' sites, a `SiteBriefingStore` with one briefing per site, `mount_site_workspace(app, projector=..., briefing_service=None, briefing_store=store)`; assert `GET /v1/site-briefings/latest` returns only the caller's organization, newest first, honours `limit`, `POST .../refresh` is 404 when no service, and `GET /v1/sites/{id}/briefings/latest` works without a copilot). Reuse the `SiteWorkspaceProjector` construction from `tests/contract/test_api_contract_sync.py` lines ~240-330.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**: router takes `briefing_store` and mounts the two GET routes when it is not None, the POST only with the service; add response model `SiteBriefingListView(CamelModel): items: list[SiteBriefing]`. In `workspace_graph.py` create `site_briefing_store = SiteBriefingStore(journal("site-briefings.jsonl"), site_store=site_store)` outside the copilot block (the copilot block reuses it), add it to `WorkspaceGraph`; in `assembly.py` build `ExternalResultBriefingProjector` when `external_result_read_projector`, `external_relative_volume_store`, `external_result_workflow_service` and `work_area_store` exist, and `bind` it; thread `site_briefing_store` through `app_factory.create_app` → `routes/operations.py` → `mount_site_workspace`. In `assembly_validation.py` keep the `site_briefing_service` rule and add `("site_briefing_store", (("site_store",),), "site_briefing_store는 site_store와 함께 주어져야 한다")`. Document `/v1/site-briefings/latest` in `openapi-core.yaml` next to the existing briefing paths with `security: [{ bearerAuth: [] }]`, `limit` query (default 20, max 200) and schema `SiteBriefingListView`.

- [ ] **Step 4: Run** the new test, `tests/contract/test_api_contract_sync.py`, `tests/contract/test_copilot_conversations.py`, `tests/contract/test_core_composition_module_migration.py`, `tests/contract/test_core_app_assembly.py` (whatever exists for assembly) → PASS.

- [ ] **Step 5: Commit** `feat(core): serve site briefings without the copilot and list latest per site`.

---

### Task 8: Dashboard surfaces for external briefings

**Files:**
- Modify: `apps/dashboard/src/lib/core-api/site-workspace.ts` (`listLatestSiteBriefings`)
- Modify: `apps/dashboard/src/lib/home-operations.ts`, `apps/dashboard/src/app/page.tsx`
- Modify: `apps/dashboard/src/app/sites/[siteId]/page.tsx` (briefing card action gating: show "KSI AI에서 질문" only if `site.aiEgressAllowed`; empty-state copy when no briefing and AI off: "아직 저장된 브리핑이 없습니다 · 외부 산출물 결과가 기록되면 자동으로 만들어집니다")
- Modify: `apps/dashboard/src/app/field/work-orders/[workOrderId]/page.tsx` (compact briefing card when the latest site briefing cites a report of this order: citation `objectType === "external-relative-volume-report"` and `objectId === latestResult.reportRef`)
- Test: `apps/dashboard/test/home-operations.test.ts` (new case), `apps/dashboard/test/site-briefing-card.test.tsx` if the card is extracted.

- [ ] **Step 1: Write the failing test** — in `home-operations.test.ts` add:

```ts
it("surfaces an external result briefing as a new result", () => {
  const updates = selectHomeRecentUpdates({
    events: [], workOrders: [], sites: [site("site-a")],
    briefings: [{ schemaVersion: "1.0", briefingId: "b-1", organizationId: "org", siteId: "site-a", status: "READY", whatChanged: "A 구역 순변화 128.0 m³", whyItMatters: "첫 결과", decisionPrompt: "결과와 근거를 검토하세요.", citations: [{ citationId: "report:r-1", objectType: "external-relative-volume-report", objectId: "r-1", label: "보고서", sourcePath: "/v1/external-relative-volume-reports/r-1", capturedFrom: null, capturedTo: null, modelVersion: null, geometryRef: null, uncertaintySummary: null }], uncertainty: "±12 m³", sourceWatermark: "external-report:sha256:a:REPORTED", missingData: [], generatedAt: "2026-09-17T00:00:00Z" }],
  });
  expect(updates[0]).toMatchObject({ kind: "EXTERNAL_RESULT_BRIEFED", siteId: "site-a" });
});
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement**: add `briefings?: readonly SiteBriefing[]` to the selector input and a candidate `{ kind: "EXTERNAL_RESULT_BRIEFED", key: \`briefing:${b.briefingId}\`, siteId, observedAt: b.generatedAt, briefing: b }` for READY briefings whose watermark starts with `external-report:`; in `page.tsx` load `settle(listLatestSiteBriefings())`, pass `briefings`, and map the new kind to a `HomeRecentUpdateView` with label "새 결과", title = `briefing.whatChanged` (first sentence, max 60 chars), detail = `briefing.decisionPrompt`, href = `/sites/${siteId}/observations/${reportRef}` where `reportRef` is the `external-relative-volume-report` citation's `objectId` (fallback `/sites/${siteId}`), `image: null`, `imageFallbackLabel: "관측 이미지 없음"`. Client: `listLatestSiteBriefings(limit = 50): Promise<{ items: SiteBriefing[] }>` calling `/v1/site-briefings/latest?limit=`.

- [ ] **Step 4: Run** `npm test`, `npx tsc --noEmit`, `npx eslint .` → PASS.

- [ ] **Step 5: Commit** `feat(dashboard): surface external result briefings on Home, site and work order`.

---

### Task 9: Rehearsal browser pass and evidence

- [ ] Relaunch the local stack (issuer, MinIO, Core from `main`, dashboard) per `.dev-data/a2/EVIDENCE.md` §6 and `docs/audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md` run2 section; re-issue snapshot/catalog windows; drive one pair decision that is BLOCKED (e.g. VISUAL_COMPARISON) and one ELIGIBLE → volume → review → approval.
- [ ] Capture screenshots: blocker card, work-order next action at each stage, site briefing card, Home recent update.
- [ ] Append a "run3 — AX-1/AX-2 browser pass" section to the audit with what was observed, then update `docs/superpowers/plans/2026-09-07-external-artifact-validation.md` execution state and the product-state Backlog (remove the next-action item).
- [ ] Run the full local gates (`ruff`, `mypy packages services tests tools`, `pytest -q`, dashboard `tsc`/`eslint`/`vitest`/`next build`) and commit `docs(audit): record AX-1/AX-2 browser pass`.

---

## Self-review

- Spec §4.1 catalog/coverage/sync → Tasks 1-2. §4.2 card → Task 3. §4.3 stage → Task 4. §5.1 record/triggers/idempotency → Tasks 5-6. §5.2 wiring/routes → Task 7. §5.3 surfaces → Task 8. §6 tests → each task plus Task 9.
- Names used consistently: `PAIR_REASON_REMEDIATIONS`, `load_external_use_blocker_catalog`, `explainExternalUseDecision`, `ExternalUseBlockerCard`, `deriveExternalWorkOrderStage`, `bind_report_listener` / `bind_review_listener` / `bind_approval_listener`, `ExternalResultBriefingProjector`, `latest_for_organization`, `listLatestSiteBriefings`, `EXTERNAL_RESULT_BRIEFED`.
