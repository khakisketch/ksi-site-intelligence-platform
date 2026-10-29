/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisCoverage } from "@/components/analysis/AnalysisCoverage";
import type { AnalysisView } from "@/lib/core-api/analysis";

const witness = {
  contractVersion: "external-relative-volume-coverage-witness.v2", rows: 2, columns: 3, rowOffset: 7, columnOffset: 11,
  selectedMaskB64: "6A==", commonValidMaskB64: "qA==", unavailableMaskB64: "QA==", thresholdExcludedMaskB64: "AA==",
  selectedCellCount: 4, commonValidCellCount: 3, unavailableCellCount: 1, thresholdExcludedCellCount: 0,
  cellAreaM2: 2, selectedAreaM2: 8, commonValidAreaM2: 6, bounds: [10, 20, 16, 24], coverageWitnessDigest: `sha256:${"a".repeat(64)}`,
};
const detail = {
  siteId: "site-1", analysisId: "analysis-1", workAreaId: "area-1", executionState: "COMPLETED",
  suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED", evidenceDigest: "evidence-1",
  result: { resultId: "result-1", reportDigest: `sha256:${"b".repeat(64)}`, numericResultIdentityDigest: `sha256:${"c".repeat(64)}`,
    metrics: { thresholdM: 0 }, coverage: { ...witness } },
} as unknown as AnalysisView;
const resource = { siteId: detail.siteId, analysisId: detail.analysisId, workAreaId: detail.workAreaId,
  resultId: detail.result!.resultId, reportDigest: detail.result!.reportDigest,
  numericResultIdentityDigest: detail.result!.numericResultIdentityDigest, coverage: witness, gridReference: null };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("calculation coverage evidence", () => {
  it("loads only on request and offers a keyboard-readable cell inspection, not an invented geographic overlay", async () => {
    const fetch = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async () => json(resource)); vi.stubGlobal("fetch", fetch);
    render(<AnalysisCoverage detail={detail} />);
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "계산·제외 영역 보기" }));
    await screen.findByRole("img", { name: /계산 범위 격자/ });
    expect(screen.getByText(/자료 없음 · 1개/)).toBeTruthy();
    expect(screen.getByText(/현장 영상이나 배경지도 위의 위치/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("확인할 열"), { target: { value: "2" } });
    expect(screen.getByText(/자료 없음 — 0으로 계산한 셀이 아닙니다/)).toBeTruthy();
    expect(screen.getByText(/기준 격자 행 7 · 열 12/)).toBeTruthy();
    expect(fetch.mock.calls[0]![0]).toBe("/api/sites/site-1/analyses/analysis-1/coverage");
  });

  it("removes previously loaded masks on permission loss and does not turn them into an empty/zero map", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(resource)).mockResolvedValueOnce(json({}, 403)));
    render(<AnalysisCoverage detail={detail} />);
    fireEvent.click(screen.getByRole("button", { name: "계산·제외 영역 보기" }));
    await screen.findByRole("img", { name: /계산 범위 격자/ });
    fireEvent.click(screen.getByRole("button", { name: "계산 범위 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/접근 권한/));
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("does not carry a diagram across result changes or accept a late response from the previous record", async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
    const { rerender } = render(<AnalysisCoverage detail={detail} />);
    fireEvent.click(screen.getByRole("button", { name: "계산·제외 영역 보기" }));
    rerender(<AnalysisCoverage detail={{ ...detail, analysisId: "analysis-2" }} />);
    resolve(json(resource));
    await waitFor(() => expect(screen.getByRole("button", { name: "계산·제외 영역 보기" })).toBeTruthy());
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("rejects mismatched result identities and preserves a recoverable error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ ...resource, resultId: "other-result" })));
    render(<AnalysisCoverage detail={detail} />);
    fireEvent.click(screen.getByRole("button", { name: "계산·제외 영역 보기" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/연결을 확인/));
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("explains unavailable current results and display budgets without fetching", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const { rerender } = render(<AnalysisCoverage detail={{ ...detail, result: null }} />);
    expect(screen.getByText(/현재 제공할 수 있는 계산 범위 근거가 없습니다/)).toBeTruthy();
    rerender(<AnalysisCoverage detail={{ ...detail, result: { ...detail.result!, coverage: { ...detail.result!.coverage, rows: 1e9 } } }} />);
    expect(screen.getByText(/화면 표시 한도/)).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });
});
