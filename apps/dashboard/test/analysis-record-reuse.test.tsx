/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnalysisRecordReuse } from "@/app/sites/[siteId]/analysis/AnalysisRecordReuse";
import type { AnalysisEvidencePage, AnalysisView } from "@/lib/core-api/analysis";

const record: AnalysisView = {
  analysisId: "analysis-1", siteId: "site-1", workAreaId: "area-1",
  baseline: { workOrderId: "work-a", submissionRef: "submission-a", revision: 3 },
  current: { workOrderId: "work-b", submissionRef: "submission-b", revision: 1 },
  executionState: "COMPLETED", suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED",
  result: {
    resultId: "result-1", reportDigest: "sha256:report", numericResultIdentityDigest: "sha256:numeric",
    computedAt: "2026-10-21T00:05:00Z", metrics: { cutM3: 0, fillM3: 800, netM3: 800, thresholdM: 0, uncertaintyM3: null },
    limitationCodes: [], coverage: { coverageWitnessDigest: "sha256:coverage", rows: 1, columns: 1,
      selectedCellCount: 1, commonValidCellCount: 1, unavailableCellCount: 0, thresholdExcludedCellCount: 0,
      cellAreaM2: 1, selectedAreaM2: 1, commonValidAreaM2: 1, bounds: [0, 0, 1, 1] },
  }, blockers: [], evidenceRevision: 2, evidenceDigest: "sha256:evidence-2", evidenceHref: "/evidence",
  coverageHref: null, createdAt: "2026-10-21T00:00:00Z",
};
const evidence: AnalysisEvidencePage = {
  analysisId: record.analysisId, evidenceRevision: 2, evidenceDigest: record.evidenceDigest, nextCursor: null,
  items: [{ kind: "CALCULATION_IDENTITY", recordId: "calc-1", digest: "sha256:calc", limitationCodes: [],
    calculation: { calculationId: "calc-1", workAreaDefinitionDigest: "sha256:area-definition",
      baselineInputDigest: "sha256:input-a", currentInputDigest: "sha256:input-b",
      policy: { policyId: "policy-1", version: 4, profileId: "profile-1", profileDigest: "sha256:profile",
        algorithmDigest: "sha256:algorithm", configDigest: "sha256:config", policyDigest: "sha256:policy" },
      runtime: { workerExecutableDigest: "sha256:exe", workerBuildDigest: "sha256:build", runtimeImageVersion: "2.0.0",
        runtimeImageOciDigest: "sha256:image", dependencyLockDigest: "sha256:lock" } } }],
};
afterEach(cleanup);

describe("record lineage and reuse disclosure", () => {
  it("keeps technical detail on demand and links the exact stored record without copying browsing hints", () => {
    const { container } = render(<AnalysisRecordReuse record={record} inputLabels={{ baseline: "10월 6일 관측", current: "10월 13일 관측" }} />);
    const detail = container.querySelector("details")!;
    expect(detail.open).toBe(false);
    fireEvent.click(screen.getByText("결과 계보·재사용 정보"));
    expect(screen.getByText("10월 6일 관측")).toBeTruthy();
    expect(screen.getByText("등록 버전 3")).toBeTruthy();
    expect(screen.getByText("submission-a")).toBeTruthy();
    expect(screen.getByText("result-1")).toBeTruthy();
    const href = container.querySelector("a")!.getAttribute("href")!;
    expect(href).toBe("/sites/site-1/analysis?workAreaId=area-1&analysisId=analysis-1");
    expect(href).not.toMatch(/visual|hint|token|returnTo/);
    expect(container.querySelector("form,button")).toBeNull();
    expect(screen.getByText(/링크 자체에 열람 권한은 없으며/)).toBeTruthy();
    expect(screen.getByText(/기록된 계산 결과와 현재 활용 가능 여부는 별개/)).toBeTruthy();
  });

  it("does not invent a missing result or unloaded calculation policy", () => {
    const { container } = render(<AnalysisRecordReuse record={{ ...record, result: null, executionState: "NOT_STARTED" }} />);
    expect(screen.getByText("기록된 계산 결과 없음")).toBeTruthy();
    expect(screen.getByText(/계산 조건을 아직 불러오지 못했습니다/)).toBeTruthy();
    expect(container.textContent).not.toContain("profile-1");
    expect(container.textContent).not.toContain("800");
  });

  it("shows profile and exact runtime from matching authoritative evidence only", () => {
    render(<AnalysisRecordReuse record={record} evidencePages={[evidence]} />);
    expect(screen.getByText("profile-1")).toBeTruthy();
    expect(screen.getByText("sha256:area-definition")).toBeTruthy();
    expect(screen.getByText("sha256:input-a")).toBeTruthy();
    expect(screen.getByText("sha256:image")).toBeTruthy();
  });

  it.each([
    { analysisId: "other-record" }, { evidenceRevision: 1 }, { evidenceDigest: "sha256:stale" },
  ])("does not join stale or foreign evidence into this result: %j", (mismatch) => {
    const { container } = render(<AnalysisRecordReuse record={record} evidencePages={[{ ...evidence, ...mismatch }]} />);
    expect(container.textContent).not.toContain("profile-1");
    expect(screen.getByText(/근거의 개정이 현재 기록과 달라/)).toBeTruthy();
  });

  it("does not pick one calculation silently from conflicting evidence pages", () => {
    render(<AnalysisRecordReuse record={record} evidencePages={[evidence, evidence]} />);
    expect(screen.queryByText("profile-1")).toBeNull();
    expect(screen.getByText(/계산 조건을 아직 불러오지 못했습니다/)).toBeTruthy();
  });

  it("provides existing API/MCP identities but neither activates access nor exports credentials", () => {
    const { container } = render(<AnalysisRecordReuse record={record} />);
    expect(container.textContent).toContain("GET /v2/sites/site-1/analyses/analysis-1/evidence");
    expect(container.textContent).toContain("ksi_get_analysis");
    expect(container.textContent).toContain('{"siteId":"site-1","analysisId":"analysis-1"}');
    expect(screen.getByText(/MCP는 전용 신원과 별도 현장 AI 반출 동의/)).toBeTruthy();
    for (const link of container.querySelectorAll("a")) expect(link.getAttribute("href")).toMatch(/^\/sites\//);
    expect(container.textContent).not.toMatch(/Bearer |AWS_|https?:\/\//);
  });
});
