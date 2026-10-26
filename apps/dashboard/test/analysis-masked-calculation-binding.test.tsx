/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalysisMaskedCalculation, boundMaskedOutputSource } from "@/app/sites/[siteId]/analysis/AnalysisMaskedCalculation";
import type { AnalysisEvidencePage, AnalysisView } from "@/lib/core-api/analysis";
import { parseMaskedCalculationDetail, type MaskedCalculationDetailWire } from "@/lib/core-api/masked-analysis";
import fixture from "./masked-wire-fixture.json";

const mocked = vi.hoisted(() => ({ current: null as unknown, available: null as unknown, sessionScope: null as unknown }));
vi.mock("@/app/sites/[siteId]/analysis/MaskedAnalysisPanel", () => ({
  MaskedAnalysisPanel: ({ onResult, sessionScope, onInvalidated }: { onResult: (value: unknown) => void; sessionScope: unknown; onInvalidated: () => void }) => {
    mocked.sessionScope = sessionScope;
    return <section>
    <button onClick={() => onResult(mocked.available)}>합성 V3 결과 읽기</button>
    <button onClick={() => onResult(mocked.current)}>합성 V3 현재 상태 읽기</button>
    <button onClick={onInvalidated}>합성 마스크 접근 불가</button>
  </section>;
  },
}));
vi.mock("@/app/sites/[siteId]/analysis/DeltaPublicationPanel", () => ({
  DeltaPublicationPanel: ({ source }: { source: { sourceCalculationIdentityDigest: string } }) =>
    <section aria-label="V3 내보내기 인계">{source.sourceCalculationIdentityDigest}</section>,
}));
afterEach(() => cleanup());

const available = parseMaskedCalculationDetail(fixture.detailViewAvailable, {
  siteId: "site-1", workAreaId: "area-1", requestId: fixture.detailViewAvailable.requestId,
});
const source = fixture.sourceCalculationIdentityDigest;
const detail = { analysisId: "v2-no-numeric", siteId: "site-1", workAreaId: "area-1", result: null,
  executionState: "FAILED", evidenceRevision: 1, evidenceDigest: `sha256:${"a".repeat(64)}` } as AnalysisView;
const pages = [{ analysisId: detail.analysisId, evidenceRevision: 1, evidenceDigest: detail.evidenceDigest,
  nextCursor: null, items: [{ kind: "AUTHORITY_REFERENCE", referenceName: "calculationIdentityDigest",
    sourceDigest: source, digest: source, recordId: "source-identity", limitationCodes: [] }] }] satisfies AnalysisEvidencePage[];

describe("masked V3 result/export composition", () => {
  it("binds exact V3 result digests without borrowing the V2 source numeric identity", () => {
    const output = boundMaskedOutputSource(source, available, "site-1", "area-1");
    expect(output?.sourceCalculationIdentityDigest).toBe(available.maskedCalculationIdentityDigest);
    expect(output?.sourceCalculationIdentityDigest).not.toBe(source);
    expect(output?.sourceNumericResultIdentityDigest).toBe(available.report!.numericResultIdentityDigest);
    expect(output?.sourceCoverageWitnessDigest).toBe(available.report!.numericResult.coverage.coverageWitnessDigest);
  });

  it.each(["scope", "source", "identity", "coverage", "unavailable"])("rejects mismatched %s before export", (change) => {
    const value = structuredClone(available);
    if (change === "scope") value.siteId = "foreign";
    if (change === "source") value.admission!.sourceCalculationIdentityDigest = `sha256:${"0".repeat(64)}`;
    if (change === "identity") value.report!.maskedCalculationIdentityDigest = `sha256:${"0".repeat(64)}`;
    if (change === "coverage") value.report!.numericResult.coverage.coverageWitnessDigest = null;
    if (change === "unavailable") value.disposition = "REASSESSMENT_REQUIRED";
    expect(boundMaskedOutputSource(source, value, "site-1", "area-1")).toBeNull();
  });

  it("removes the V3 export handoff when a current read loses admission, without needing V2 numeric success", () => {
    mocked.available = available;
    mocked.current = { ...available, disposition: "REASSESSMENT_REQUIRED", report: null } as MaskedCalculationDetailWire;
    render(<AnalysisMaskedCalculation detail={detail} pages={pages} workAreaName="합성 구역" canRequest
      maskBudgetBytes={1000000} delivery={{ lifetimeSeconds: 60, downloadBudgetBytes: 1000000 }} />);
    fireEvent.click(screen.getByText("독립 마스크로 별도 계산 · V3"));
    fireEvent.click(screen.getByRole("button", { name: "합성 V3 결과 읽기" }));
    expect(screen.getByRole("region", { name: "V3 내보내기 인계" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "합성 V3 현재 상태 읽기" }));
    expect(screen.queryByRole("region", { name: "V3 내보내기 인계" })).toBeNull();
  });

  it("clears a stale export after mask access is denied or inspection is rejected", () => {
    mocked.available = available;
    render(<AnalysisMaskedCalculation detail={detail} pages={pages} workAreaName="합성 구역" canRequest
      maskBudgetBytes={1000000} delivery={{ lifetimeSeconds: 60, downloadBudgetBytes: 1000000 }} />);
    fireEvent.click(screen.getByText("독립 마스크로 별도 계산 · V3"));
    fireEvent.click(screen.getByRole("button", { name: "합성 V3 결과 읽기" }));
    expect(screen.getByRole("region", { name: "V3 내보내기 인계" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "합성 마스크 접근 불가" }));
    expect(screen.queryByRole("region", { name: "V3 내보내기 인계" })).toBeNull();
  });

  it("passes only the server session scope and drops another principal's in-memory export", () => {
    mocked.available = available;
    const props = { detail, pages, workAreaName: "합성 구역", canRequest: true, maskBudgetBytes: 1000000,
      delivery: { lifetimeSeconds: 60, downloadBudgetBytes: 1000000 } };
    const { rerender } = render(<AnalysisMaskedCalculation {...props}
      sessionScope={{ organizationId: "org-1", principalId: "operator-a" }} />);
    fireEvent.click(screen.getByText("독립 마스크로 별도 계산 · V3"));
    expect(mocked.sessionScope).toEqual({ organizationId: "org-1", principalId: "operator-a" });
    fireEvent.click(screen.getByRole("button", { name: "합성 V3 결과 읽기" }));
    expect(screen.getByRole("region", { name: "V3 내보내기 인계" })).toBeTruthy();
    rerender(<AnalysisMaskedCalculation {...props}
      sessionScope={{ organizationId: "org-1", principalId: "operator-b" }} />);
    expect(mocked.sessionScope).toEqual({ organizationId: "org-1", principalId: "operator-b" });
    expect(screen.queryByRole("region", { name: "V3 내보내기 인계" })).toBeNull();
    rerender(<AnalysisMaskedCalculation {...props} />);
    expect(mocked.sessionScope).toBeNull();
  });

  it("offers an explicit read-only next action before the AP source evidence is loaded", () => {
    const load = vi.fn();
    render(<AnalysisMaskedCalculation detail={detail} pages={[]} workAreaName="합성 구역" canRequest
      maskBudgetBytes={1000000} delivery={null} onLoadSource={load} />);
    fireEvent.click(screen.getByText("독립 마스크로 별도 계산 · V3"));
    expect(load).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "원본 근거 불러오기" }));
    expect(load).toHaveBeenCalledOnce();
  });
});
