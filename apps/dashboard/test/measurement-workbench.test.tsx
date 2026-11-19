/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SurfaceProfileComparison, SurfaceProfileResult } from "@/lib/core-api/measurement-types";
import { MeasurementWorkbench, type WorkbenchProps } from "@/app/sites/[siteId]/measurements/MeasurementWorkbench";

const mockedNavigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mockedNavigation.replace }) }));

const DIGEST = `sha256:${"a".repeat(64)}`;
const FEATURE_ID = `mf-${"1".repeat(32)}`;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

// 0 / 7.5 / 15 / 22.5 / 30 m. 15 m 지점은 자료가 없다. 높이는 100 + 0.5 * 번호 + offset.
function result(offset: number, nodataAt: number | null = 2, overrides: Partial<SurfaceProfileResult> = {}): SurfaceProfileResult {
  const samples = Array.from({ length: 5 }, (_, i) => (i === nodataAt
    ? { index: i, distanceM: i * 7.5, x: 200000 + i * 7.5, y: 500000 + i, elevationM: null, invalidReason: "NODATA" as const }
    : { index: i, distanceM: i * 7.5, x: 200000 + i * 7.5, y: 500000 + i, elevationM: 100 + offset + i * 0.5, invalidReason: null }));
  const known = samples.filter((row) => row.elevationM !== null).length;
  return {
    assetRef: `ksa-v1-${(offset === 0 ? "1" : "3").repeat(64)}`, lineDigest: DIGEST, feature: { featureId: FEATURE_ID, revision: 2, lineDigest: DIGEST },
    horizontalCrs: "EPSG:5186", lineLengthM: 30, sampleSpacingM: 7.5, samples, validCount: known, unknownCount: 5 - known,
    minimumM: 100 + offset, maximumM: 102 + offset,
    resultDigest: `sha256:${(offset === 0 ? "b" : "c").repeat(64)}`,
    ...overrides,
  };
}

function props(overrides: Partial<WorkbenchProps> = {}): WorkbenchProps {
  return {
    siteId: "site-1",
    workAreaId: "area-1",
    features: [{ featureId: FEATURE_ID, label: "북쪽 경사면 · 개정 2" }],
    selectedFeatureId: FEATURE_ID,
    featureName: "북쪽 경사면",
    featureRevision: 2,
    featureLineDigest: DIGEST,
    canCompare: true,
    canRequest: true,
    dateOptions: [{ jobId: `spj-${"1".repeat(32)}`, label: "2026-03-14" }, { jobId: `spj-${"3".repeat(32)}`, label: "2026-11-02" }],
    refJobId: `spj-${"1".repeat(32)}`,
    curJobId: `spj-${"3".repeat(32)}`,
    baseline: { jobId: `spj-${"1".repeat(32)}`, label: "2026-03-14", result: result(0) },
    current: { jobId: `spj-${"3".repeat(32)}`, label: "2026-11-02", result: result(0.8) },
    unavailable: [],
    notes: [],
    ...overrides,
  };
}

function mockFreshDateResults(input: WorkbenchProps, deniedId?: string) {
  return vi.spyOn(globalThis, "fetch").mockClear().mockImplementation(async (url) => {
    const jobId = String(url).split("/").at(-2);
    const item = [input.baseline, input.current].find((entry) => entry?.jobId === jobId);
    if (!item || jobId === deniedId) return new Response(null, { status: 403 });
    return Response.json({
      job: {
        jobId, siteId: input.siteId, workAreaId: input.workAreaId,
        assetRef: item.result.assetRef, feature: item.result.feature, createdAt: "2026-11-19T05:00:00Z",
        executionState: "COMPLETED", availability: "AVAILABLE", reason: null,
        receipt: item.vertical ? { verticalReference: item.vertical } : null,
      },
      result: item.result,
    });
  });
}

beforeEach(() => {
  mockedNavigation.replace.mockReset();
  // jsdom은 레이아웃이 없다. 그래프가 가로 360 단위로 그려진 화면을 흉내 낸다.
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 360, bottom: 230, width: 360, height: 230, toJSON: () => ({}) });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const hit = () => screen.getByTestId("profile-chart-hit");
const pressed = (key: string, init: KeyboardEventInit = {}) => fireEvent.keyDown(hit(), { key, ...init });
// jsdom의 PointerEvent는 좌표를 싣지 않는다. 좌표가 있는 MouseEvent에 포인터 이벤트 이름을 붙여 보낸다.
const pointer = (type: "pointerdown" | "pointermove" | "pointerup", clientX: number) => fireEvent(hit(), new MouseEvent(type, { clientX, clientY: 100, bubbles: true }));
const live = () => document.querySelector('[aria-live="polite"]')!.textContent ?? "";

describe("측정 선 작업대", () => {
  it("두 단면 선택만으로는 비교 요청을 보내지 않고, 명시적으로 눌렀을 때 Core 판정을 읽는다", async () => {
    const blocked: SurfaceProfileComparison = {
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: "spj-" + "1".repeat(32),
      currentJobId: "spj-" + "3".repeat(32),
      decisionId: "decision-1",
      decisionDigest: DIGEST,
      verdict: "BLOCKED",
      reasons: ["EVIDENCE_INDEPENDENCE_UNATTESTED"],
      remediations: ["ATTEST_INDEPENDENT_EVIDENCE"],
      result: null,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify(blocked), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MeasurementWorkbench {...props()} />);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "두 시점 높이차 확인" }));
    expect(await screen.findByText(/재구성과 독립적으로 측정했다는 별도 확인/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledOnce();
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ baselineJobId: blocked.baselineJobId, currentJobId: blocked.currentJobId });
  });

  it("차단 판정의 조치와 자료 주소를 복사하고 선택 변경 때 복사 확인을 지운다", async () => {
    const selected = props();
    const blocked: SurfaceProfileComparison = {
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: selected.baseline!.jobId,
      currentJobId: selected.current!.jobId,
      decisionId: "decision-copy-blocked",
      decisionDigest: DIGEST,
      verdict: "BLOCKED",
      reasons: ["COMPATIBILITY_MAPPING_MISSING"],
      remediations: ["AUTHORIZE_COMPATIBILITY_MAPPING"],
      result: null,
    };
    const fetchMock = vi.fn(async () => Response.json(blocked));
    vi.stubGlobal("fetch", fetchMock);
    const writeText = vi.fn(async (text: string) => {
      expect(typeof text).toBe("string");
    });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    window.history.replaceState(
      {},
      "",
      `/sites/site-1/measurements?token=do-not-copy&extra=private`,
    );
    const view = render(<MeasurementWorkbench {...selected} />);
    fireEvent.click(screen.getByRole("button", { name: "두 시점 높이차 확인" }));
    await screen.findByText(/호환성 매핑이 등록되지 않았습니다/);
    fireEvent.click(screen.getByRole("button", { name: "판정 내용 복사" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledOnce());

    const copied = writeText.mock.calls[0]![0];
    expect(copied).toContain("2026-03-14");
    expect(copied).toContain("2026-11-02");
    expect(copied).toContain(selected.baseline!.result.assetRef);
    expect(copied).toContain(selected.current!.result.assetRef);
    expect(copied).toContain("AUTHORIZE_COMPATIBILITY_MAPPING");
    expect(copied).toContain("담당 ");
    expect(copied).toContain("판정·조치 코드 ");
    expect(copied).not.toContain("do-not-copy");
    expect(copied).not.toContain("extra=private");
    expect(copied).not.toContain("100.00");
    const address = new URL(copied.trim().split("\n").at(-1)!);
    expect(address.origin).toBe(window.location.origin);
    expect(Array.from(address.searchParams.keys())).toEqual([
      "workAreaId", "feature", "ref", "cur", "comparison",
    ]);
    expect(await screen.findByText("판정 내용을 복사했습니다.")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledOnce();

    const nextCurrentId = `spj-${"5".repeat(32)}`;
    view.rerender(
      <MeasurementWorkbench
        {...selected}
        curJobId={nextCurrentId}
        current={{ ...selected.current!, jobId: nextCurrentId }}
      />,
    );
    expect(screen.queryByText("판정 내용을 복사했습니다.")).toBeNull();
    expect(screen.queryByRole("button", { name: "판정 내용 복사" })).toBeNull();
  });

  it("클립보드가 막히면 판정 내용을 읽기 전용 영역에 선택해 둔다", async () => {
    const selected = props();
    const blocked: SurfaceProfileComparison = {
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: selected.baseline!.jobId,
      currentJobId: selected.current!.jobId,
      decisionId: "decision-copy-fallback",
      decisionDigest: DIGEST,
      verdict: "BLOCKED",
      reasons: ["COMPATIBILITY_MAPPING_MISSING"],
      remediations: ["AUTHORIZE_COMPATIBILITY_MAPPING"],
      result: null,
    };
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(blocked)));
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("clipboard denied")) },
    });
    render(<MeasurementWorkbench {...selected} />);
    fireEvent.click(screen.getByRole("button", { name: "두 시점 높이차 확인" }));
    await screen.findByText(/호환성 매핑이 등록되지 않았습니다/);
    fireEvent.click(screen.getByRole("button", { name: "판정 내용 복사" }));

    const fallback = await screen.findByRole("textbox", { name: "복사할 판정 내용" }) as HTMLTextAreaElement;
    expect(fallback.readOnly).toBe(true);
    expect(document.activeElement).toBe(fallback);
    expect(fallback.selectionStart).toBe(0);
    expect(fallback.selectionEnd).toBe(fallback.value.length);
    expect(fallback.value).toContain("기준 자료 2026-03-14");
    expect(fallback.value).toContain("현재 자료 2026-11-02");
  });

  it("저장된 비교가 새로 고침으로 바뀌면 이전 판정의 수치를 남기지 않는다", () => {
    const saved = (decisionDigest: string, verdict: "ELIGIBLE" | "BLOCKED"): SurfaceProfileComparison => ({
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: "spj-" + "1".repeat(32),
      currentJobId: "spj-" + "3".repeat(32),
      decisionId: `decision-${verdict.toLowerCase()}`,
      decisionDigest,
      verdict,
      reasons: verdict === "ELIGIBLE" ? ["USE_ELIGIBLE"] : ["COMPATIBILITY_MAPPING_MISSING"],
      remediations: verdict === "ELIGIBLE" ? ["CURRENT_DEPENDENCIES_RETAINED"] : ["AUTHORIZE_COMPATIBILITY_MAPPING"],
      result: verdict === "ELIGIBLE"
        ? {
            comparisonDigest: DIGEST,
            baselineResultDigest: DIGEST,
            currentResultDigest: "sha256:" + "b".repeat(64),
            samples: [
              { distanceM: 0, baselineM: 100, currentM: 100, differenceM: 0, invalidReason: null },
              { distanceM: 7.5, baselineM: 101, currentM: 102, differenceM: 1, invalidReason: null },
            ],
            validCount: 2,
            largestRiseM: 1,
            largestDropM: null,
          }
        : null,
    });
    const view = render(<MeasurementWorkbench {...props({ savedComparison: saved("sha256:" + "b".repeat(64), "ELIGIBLE") })} />);
    expect(screen.getByText("1.00")).toBeTruthy();

    // 승인이 철회되어 서버가 저장된 비교를 내려주지 않는다.
    view.rerender(<MeasurementWorkbench {...props({ savedComparison: null })} />);
    expect(screen.queryByText("1.00")).toBeNull();
    expect(screen.getByRole("button", { name: "두 시점 높이차 확인" })).toBeTruthy();

    // 다른 판정으로 바뀌면 그 판정을 보여 준다.
    view.rerender(<MeasurementWorkbench {...props({ savedComparison: saved("sha256:" + "c".repeat(64), "BLOCKED") })} />);
    expect(screen.getByText(/호환성 매핑이 등록되지 않았습니다/)).toBeTruthy();
    expect(screen.queryByText("1.00")).toBeNull();
  });

  it("완료 쌍 비교는 자료 읽기 권한으로 가능하고 표본 재요청 권한은 요구하지 않는다", () => {
    render(<MeasurementWorkbench {...props({ canRequest: false })} />);
    expect(screen.getByRole("button", { name: "두 시점 높이차 확인" })).toBeTruthy();
  });

  it("정상 BLOCKED 뒤의 명시적 재확인은 새 멱등 키로 다시 판정한다", async () => {
    const blocked: SurfaceProfileComparison = {
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: "spj-" + "1".repeat(32),
      currentJobId: "spj-" + "3".repeat(32),
      decisionId: "decision-blocked",
      decisionDigest: DIGEST,
      verdict: "BLOCKED",
      reasons: ["COMPATIBILITY_MAPPING_MISSING"],
      remediations: ["AUTHORIZE_COMPATIBILITY_MAPPING"],
      result: null,
    };
    const eligible: SurfaceProfileComparison = {
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: blocked.baselineJobId,
      currentJobId: blocked.currentJobId,
      decisionId: "decision-eligible",
      decisionDigest: "sha256:" + "b".repeat(64),
      verdict: "ELIGIBLE",
      reasons: ["USE_ELIGIBLE"],
      remediations: ["CURRENT_DEPENDENCIES_RETAINED"],
      result: {
        comparisonDigest: DIGEST,
        baselineResultDigest: DIGEST,
        currentResultDigest: "sha256:" + "b".repeat(64),
        samples: [
          { distanceM: 0, baselineM: 100, currentM: 100, differenceM: 0, invalidReason: null },
          { distanceM: 7.5, baselineM: 101, currentM: 102, differenceM: 1, invalidReason: null },
        ],
        validCount: 2,
        largestRiseM: 1,
        largestDropM: null,
      },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(blocked), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(eligible), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MeasurementWorkbench {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "두 시점 높이차 확인" }));
    expect(await screen.findByText(/호환성 매핑이 등록되지 않았습니다/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다시 확인" }));
    expect(await screen.findByText("1.00")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "판정 내용 복사" })).toBeNull();
    expect(screen.getByRole("link", { name: "이 비교의 고유 주소" })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstKey = (fetchMock.mock.calls[0]![1]?.headers as Record<string, string>)["Idempotency-Key"];
    const secondKey = (fetchMock.mock.calls[1]![1]?.headers as Record<string, string>)["Idempotency-Key"];
    expect(firstKey).toBeTruthy();
    expect(secondKey).toBeTruthy();
    expect(secondKey).not.toBe(firstKey);
  });

  it("Core 표본의 0과 미상 값을 구분하고 CSV 전에 같은 비교 판정을 다시 읽는다", async () => {
    const eligible: SurfaceProfileComparison = {
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: "spj-" + "1".repeat(32),
      currentJobId: "spj-" + "3".repeat(32),
      decisionId: "decision-2",
      decisionDigest: DIGEST,
      verdict: "ELIGIBLE",
      reasons: ["USE_ELIGIBLE"],
      remediations: ["CURRENT_DEPENDENCIES_RETAINED"],
      result: {
        comparisonDigest: DIGEST,
        baselineResultDigest: DIGEST,
        currentResultDigest: "sha256:" + "b".repeat(64),
        samples: [
          { distanceM: 0, baselineM: 100, currentM: 100, differenceM: 0, invalidReason: null },
          { distanceM: 7.5, baselineM: 101, currentM: 102, differenceM: 1, invalidReason: null },
          { distanceM: 15, baselineM: 102, currentM: null, differenceM: null, invalidReason: "CURRENT_UNAVAILABLE" },
          { distanceM: 22.5, baselineM: 103, currentM: 102.5, differenceM: -0.5, invalidReason: null },
          { distanceM: 30, baselineM: 104, currentM: 103, differenceM: -1, invalidReason: null },
        ],
        validCount: 4,
        largestRiseM: 1,
        largestDropM: -1,
      },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(eligible), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(eligible), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    let blob: Blob | null = null;
    const originalCreate = URL.createObjectURL;
    URL.createObjectURL = vi.fn((value: Blob) => { blob = value; return "blob:comparison"; });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    try {
      const safeCsvProps = props({ baseline: { ...props().baseline!, label: "=1+1 · 2026-03-14" } });
      const { container } = render(<MeasurementWorkbench {...safeCsvProps} />);
      fireEvent.click(screen.getByRole("button", { name: "두 시점 높이차 확인" }));
      expect(await screen.findByText("0.00")).toBeTruthy();
      expect(screen.getByText(/현재 자료 없음/)).toBeTruthy();
      expect(screen.getByTestId("profile-difference-zero")).toBeTruthy();
      expect(container.querySelectorAll('[data-series="difference"] path[fill="none"]')).toHaveLength(2);
      expect(screen.getByText("+1.00 m")).toBeTruthy();
      expect(screen.getByText("−1.00 m")).toBeTruthy();
      const differenceHit = screen.getByTestId("profile-difference-chart-hit");
      expect(differenceHit.closest("svg")?.getAttribute("class")).toContain("max-w-[360px]");
      expect(screen.getByTestId("profile-difference-zero").getAttribute("stroke")).toBe("var(--accent)");
      expect(screen.getByRole("region", { name: "거리별 두 시점 높이차 표" }).getAttribute("tabindex")).toBe("0");
      fireEvent.keyDown(differenceHit, { key: "ArrowRight" });
      expect(screen.getByTestId("profile-board-probe")).toBeTruthy();
      expect(screen.getByText(/0\.0 m · 높이차 0\.00 m/)).toBeTruthy();
      fireEvent.keyDown(differenceHit, { key: "ArrowRight" });
      expect(screen.getByText(/7\.5 m · 높이차 \+1\.00 m/)).toBeTruthy();
      fireEvent.keyDown(differenceHit, { key: "ArrowRight" });
      expect(screen.getByText(/15\.0 m · 값 없음 · 현재 자료 없음/)).toBeTruthy();
      const datePanel = screen.getByRole("complementary", { name: "단면" });
      const comparisonPanel = screen.getByRole("region", { name: "두 시점 높이차" });
      expect(datePanel.compareDocumentPosition(comparisonPanel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(datePanel.className).toContain("lg:row-span-2");
      expect(container.firstElementChild?.className).toContain("lg:grid-rows-[auto_auto]");
      fireEvent.click(screen.getByRole("button", { name: "높이차 CSV 내보내기" }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
      expect(fetchMock.mock.calls[1]![0]).toContain("decision_id=decision-2");
      expect(click).toHaveBeenCalledOnce();
      const csv = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.readAsText(blob!);
      });
      expect(csv).toContain("comparison_digest");
      expect(csv).toContain("baseline_result_digest");
      expect(csv).toContain("current_result_digest");
      expect(csv).toContain("baseline_asset_ref");
      expect(csv).toContain("current_asset_ref");
      expect(csv).toContain("baseline_capture_label");
      expect(csv).toContain("2026-03-14");
      expect(csv).toContain("2026-11-02");
      expect(csv).toContain("\"'=1+1 · 2026-03-14\"");
      expect(csv).toContain("feature_revision");
      expect(csv).toContain("difference_definition");
      expect(csv).toContain("CURRENT_UNAVAILABLE");
    } finally {
      URL.createObjectURL = originalCreate;
    }
  });

  it("표본 간격이 다르면 더 거친 기존 간격으로 필요한 날짜만 다시 요청하고 선택을 보존한다", async () => {
    const selected = props();
    const newJobId = `spj-${"5".repeat(32)}`;
    const newJob = {
      jobId: newJobId,
      assetRef: selected.baseline!.result.assetRef,
      siteId: selected.siteId,
      workAreaId: selected.workAreaId,
      feature: { featureId: selected.selectedFeatureId, revision: selected.featureRevision, lineDigest: selected.featureLineDigest },
      createdAt: "2026-11-19T00:00:00Z",
      executionState: "QUEUED",
      availability: "NOT_READY",
      reason: null,
    };
    window.history.replaceState({}, "", `/sites/site-1/measurements?workAreaId=area-1&feature=${FEATURE_ID}&ref=${selected.refJobId}&cur=${selected.curJobId}`);
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ job: newJob }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MeasurementWorkbench {...selected} current={{ ...selected.current!, result: result(0.8, 2, { sampleSpacingM: 15 }) }} />);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/공통 간격 15\.000 m에 맞춰 기준 자료만 다시 읽으면/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /공통 표본 간격으로 다시 읽기 · 기준/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const [requestUrl, init] = fetchMock.mock.calls[0]!;
    expect(requestUrl).toContain("/surface-profile-requests");
    const request = JSON.parse(String(init?.body));
    expect(request).toEqual({ assetRef: selected.baseline!.result.assetRef, feature: { featureId: FEATURE_ID, revision: 2, lineDigest: DIGEST }, sampleSpacingM: 15 });
    expect((init?.headers as Record<string, string>)?.["Idempotency-Key"]).toMatch(/^console-/);
    await waitFor(() => expect(mockedNavigation.replace).toHaveBeenCalledOnce());
    const [href, options] = mockedNavigation.replace.mock.calls[0]!;
    const url = new URL(String(href), "http://localhost");
    expect(url.searchParams.get("ref")).toBe(newJobId);
    expect(url.searchParams.get("cur")).toBe(selected.curJobId);
    expect(options).toEqual({ scroll: false });
  });

  it("날짜가 바뀌면 진행 중인 재요청이 이전 쌍으로 URL을 바꾸지 않는다", async () => {
    const selected = props();
    const pending = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>(() => pending.promise);
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<MeasurementWorkbench {...selected} current={{ ...selected.current!, result: result(0.8, 2, { sampleSpacingM: 15 }) }} />);
    fireEvent.click(screen.getByRole("button", { name: /공통 표본 간격으로 다시 읽기 · 기준/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const signal = (fetchMock.mock.calls[0]![1] as RequestInit).signal!;

    const nextBaselineId = `spj-${"5".repeat(32)}`;
    view.rerender(<MeasurementWorkbench {...selected} refJobId={nextBaselineId} baseline={{ ...selected.baseline!, jobId: nextBaselineId }} current={{ ...selected.current!, result: result(0.8, 2, { sampleSpacingM: 15 }) }} />);
    expect(signal.aborted).toBe(true);
    await act(async () => {
      pending.resolve(Response.json({ job: { jobId: `spj-${"7".repeat(32)}` } }));
      await pending.promise;
      await Promise.resolve();
    });
    expect(mockedNavigation.replace).not.toHaveBeenCalled();
  });

  it("권한 철회가 CSV 재확인에서 발견되면 기존 숫자를 숨기고 새 비교 안내를 보인다", async () => {
    const eligible: SurfaceProfileComparison = {
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: "spj-" + "1".repeat(32),
      currentJobId: "spj-" + "3".repeat(32),
      decisionId: "decision-withdrawn",
      decisionDigest: DIGEST,
      verdict: "ELIGIBLE",
      reasons: ["USE_ELIGIBLE"],
      remediations: ["CURRENT_DEPENDENCIES_RETAINED"],
      result: {
        comparisonDigest: DIGEST,
        baselineResultDigest: DIGEST,
        currentResultDigest: "sha256:" + "b".repeat(64),
        samples: [
          { distanceM: 0, baselineM: 100, currentM: 100, differenceM: 0, invalidReason: null },
          { distanceM: 7.5, baselineM: 101, currentM: 102, differenceM: 1, invalidReason: null },
        ],
        validCount: 2,
        largestRiseM: 1,
        largestDropM: null,
      },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(eligible), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: "PROFILE_COMPARISON_NO_LONGER_ELIGIBLE" }), { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MeasurementWorkbench {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "두 시점 높이차 확인" }));
    expect(await screen.findByText("1.00", {}, { timeout: 1000 })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "높이차 CSV 내보내기" }));
    expect(await screen.findByText(/현재 비교 승인이 철회되었거나 자료가 바뀌었습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "높이차 CSV 내보내기" })).toBeNull();
    expect(screen.queryByText("1.00")).toBeNull();
    expect(screen.getByRole("button", { name: "두 시점 높이차 확인" })).toBeTruthy();
  });

  it("날짜가 바뀌면 진행 중인 CSV 재확인이 이전 쌍을 내려받지 않는다", async () => {
    const selected = props();
    const eligible: SurfaceProfileComparison = {
      contractVersion: "surface-profile-comparison.v1",
      baselineJobId: selected.baseline!.jobId,
      currentJobId: selected.current!.jobId,
      decisionId: "decision-aborted-export",
      decisionDigest: DIGEST,
      verdict: "ELIGIBLE",
      reasons: ["USE_ELIGIBLE"],
      remediations: ["CURRENT_DEPENDENCIES_RETAINED"],
      result: {
        comparisonDigest: DIGEST,
        baselineResultDigest: DIGEST,
        currentResultDigest: "sha256:" + "b".repeat(64),
        samples: [
          { distanceM: 0, baselineM: 100, currentM: 100, differenceM: 0, invalidReason: null },
          { distanceM: 7.5, baselineM: 101, currentM: 102, differenceM: 1, invalidReason: null },
        ],
        validCount: 2,
        largestRiseM: 1,
        largestDropM: null,
      },
    };
    const pending = deferred<Response>();
    const fetchMock = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => init?.method === "POST"
      ? Promise.resolve(Response.json(eligible))
      : pending.promise);
    vi.stubGlobal("fetch", fetchMock);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const view = render(<MeasurementWorkbench {...selected} />);
    fireEvent.click(screen.getByRole("button", { name: "두 시점 높이차 확인" }));
    await screen.findByRole("button", { name: "높이차 CSV 내보내기" });
    fireEvent.click(screen.getByRole("button", { name: "높이차 CSV 내보내기" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const signal = (fetchMock.mock.calls[1]![1] as RequestInit).signal!;

    const nextCurrentId = `spj-${"5".repeat(32)}`;
    view.rerender(<MeasurementWorkbench {...selected} curJobId={nextCurrentId} current={{ ...selected.current!, jobId: nextCurrentId }} />);
    expect(signal.aborted).toBe(true);
    await act(async () => {
      pending.resolve(Response.json(eligible));
      await pending.promise;
      await Promise.resolve();
    });
    expect(click).not.toHaveBeenCalled();
  });

  it("모르는 지점에서 선을 끊는다(이웃 값이나 0으로 잇지 않는다)", () => {
    const { container } = render(<MeasurementWorkbench {...props()} />);
    for (const key of ["cur", "ref"]) {
      expect(container.querySelectorAll(`[data-series="${key}"] path[fill="none"]`)).toHaveLength(2);
    }
  });

  it("두 날짜와 값 없는 이유를 보여 준다", () => {
    render(<MeasurementWorkbench {...props()} />);
    expect((screen.getByLabelText("기준") as HTMLSelectElement).selectedOptions[0]?.textContent).toBe("2026-03-14");
    const chips = screen.getByRole("list", { name: "표시 중인 날짜" });
    expect(chips.textContent).toContain("기준 2026-03-14");
    expect(chips.textContent).toContain("현재 2026-11-02");
    const facts = screen.getByRole("complementary").querySelector("dl")!;
    expect(facts.textContent).toContain("한국 중부원점 TM · EPSG:5186");
    expect(facts.textContent).toContain("기준 4");
    expect(facts.textContent).toContain("자료 없음 1");
    expect(facts.textContent).toContain("평면 거리");
  });

  it("자료 상세에서 시작한 비교는 현재 자료와 선 선택을 고정하고 자료 참조를 유지한다", () => {
    const selected = props();
    const repeatedSourceJob = "spj-" + "4".repeat(32);
    const sourceAssetRef = selected.current!.result.assetRef;
    render(<MeasurementWorkbench {...selected}
      sourceAssetRef={sourceAssetRef}
      dateOptions={[
        { ...selected.dateOptions[0]!, assetRef: selected.baseline!.result.assetRef },
        { ...selected.dateOptions[1]!, assetRef: sourceAssetRef },
        { jobId: repeatedSourceJob, label: "같은 자료 다시 읽기", assetRef: sourceAssetRef },
        { jobId: "spj-" + "5".repeat(32), label: "출처 미확인" },
      ]}
      featureChooserExternal
    />);

    const form = screen.getByLabelText("기준").closest("form")!;
    expect((screen.getByLabelText("기준") as HTMLSelectElement).selectedOptions[0]?.value).toBe(selected.baseline!.jobId);
    expect(screen.queryByRole("option", { name: "출처 미확인" })).toBeNull();
    expect((form.querySelector('input[name="assetRef"]') as HTMLInputElement).value).toBe(sourceAssetRef);
    expect((form.querySelector('input[name="cur"]') as HTMLInputElement).value).toBe(selected.current!.jobId);
    expect(form.querySelector('select[name="cur"]')).toBeNull();
    expect(form.querySelector('select[name="feature"]')).toBeNull();
    expect(form.querySelector('select[name="ref"] option[value="' + selected.current!.jobId + '"]')).toBeNull();
    expect(form.querySelector('select[name="ref"] option[value="' + repeatedSourceJob + '"]')).toBeNull();
    expect(form.textContent).toContain("현재 · 선택한 자료");
    expect(form.textContent).toContain("2026-11-02");
  });

  it("선택 자료의 현재 단면이 없으면 이전 기준 결과를 열지 않는다", () => {
    render(<MeasurementWorkbench {...props()} sourceAssetRef={`ksa-v1-${"9".repeat(64)}`} current={null} />);
    expect(screen.getByText(/선택한 자료의 단면을 먼저 읽으면/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "표시 중인 날짜" })).toBeNull();
  });

  it("키보드로 지점을 읽고 같은 지점이 보드에 표시된다", () => {
    render(<MeasurementWorkbench {...props()} />);
    hit().focus();
    pressed("ArrowRight");
    expect(screen.getByText(/0\.0 m · 기준 100\.00 m · 현재 100\.80 m/)).toBeTruthy();
    expect(screen.getByTestId("profile-board-probe")).toBeTruthy();
    pressed("ArrowRight");
    pressed("ArrowRight");
    // 15 m 지점은 자료가 없다. 값 대신 이유를 말한다.
    expect(screen.getByText(/15\.0 m · 기준 값 없음 · 자료 없음 · 현재 값 없음 · 자료 없음/)).toBeTruthy();
  });

  it("Shift와 화살표로 구간을 고르면 높이 차와 기울기를 읽는다", () => {
    render(<MeasurementWorkbench {...props()} />);
    hit().focus();
    pressed("ArrowRight");
    for (let step = 0; step < 3; step += 1) pressed("ArrowRight", { shiftKey: true });
    // 0~22.5 m: 유효 처음 100.0, 유효 끝 101.5 → +1.50 m, 22.5 m 동안 6.67 %
    expect(live()).toContain("0.0–22.5 m 구간 · 길이 22.5 m");
    expect(live()).toContain("기준 +1.50 m (+6.7 %)");
    expect(live()).toContain("현재 +1.50 m (+6.7 %)");
    expect(screen.getByTestId("profile-board-range")).toBeTruthy();
  });

  it("Esc와 해제 버튼으로 구간을 지운다", () => {
    render(<MeasurementWorkbench {...props()} />);
    hit().focus();
    pressed("ArrowRight");
    pressed("ArrowRight", { shiftKey: true });
    expect(screen.queryByTestId("profile-board-range")).toBeTruthy();
    pressed("Escape");
    expect(screen.queryByTestId("profile-board-range")).toBeNull();
    pressed("ArrowRight");
    pressed("ArrowRight", { shiftKey: true });
    fireEvent.click(screen.getByRole("button", { name: "해제" }));
    expect(screen.queryByTestId("profile-board-range")).toBeNull();
  });

  it("끌어서 구간을 고른다", () => {
    render(<MeasurementWorkbench {...props()} />);
    // 가로 360 중 그래프 영역은 40..348. 0 m는 40, 30 m는 348 부근이다.
    pointer("pointerdown", 40);
    pointer("pointermove", 348);
    pointer("pointerup", 348);
    expect(live()).toContain("0.0–30.0 m 구간 · 길이 30.0 m");
  });

  it("누르기만 하고 끌지 않으면 구간을 만들지 않는다", () => {
    render(<MeasurementWorkbench {...props()} />);
    pointer("pointerdown", 200);
    pointer("pointerup", 200);
    expect(screen.queryByTestId("profile-board-range")).toBeNull();
    expect(screen.queryByTestId("profile-chart-range")).toBeNull();
    expect(live()).not.toContain("구간");
  });

  it("Shift 없이 지점을 옮기면 고른 구간을 지운다", () => {
    render(<MeasurementWorkbench {...props()} />);
    hit().focus();
    pressed("ArrowRight");
    pressed("ArrowRight", { shiftKey: true });
    expect(screen.queryByTestId("profile-chart-range")).toBeTruthy();
    pressed("ArrowRight");
    expect(screen.queryByTestId("profile-chart-range")).toBeNull();
    expect(screen.queryByTestId("profile-board-range")).toBeNull();
  });

  it("세로 비율을 바꾸면 고른 구간을 지운다(축이 달라지므로)", () => {
    render(<MeasurementWorkbench {...props()} />);
    hit().focus();
    pressed("ArrowRight");
    pressed("ArrowRight", { shiftKey: true });
    expect(screen.queryByTestId("profile-chart-range")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "1:1" }));
    expect(screen.queryByTestId("profile-chart-range")).toBeNull();
    expect(screen.queryByTestId("profile-board-range")).toBeNull();
  });

  it("유효 지점이 모자란 구간은 값을 만들지 않는다", () => {
    render(<MeasurementWorkbench {...props()} />);
    hit().focus();
    pressed("ArrowRight");
    pressed("ArrowRight");
    // 7.5~15 m 구간: 15 m 지점은 값이 없어 유효 지점이 7.5 m 하나뿐이다.
    pressed("ArrowRight", { shiftKey: true });
    expect(live()).toContain("7.5–15.0 m 구간");
    expect(live()).toContain("기준 값 부족");
    expect(live()).toContain("현재 값 부족");
  });

  it("1:1로 바꾸면 그래프가 실제 비율로 다시 그려진다", () => {
    const { container } = render(<MeasurementWorkbench {...props()} />);
    expect(container.textContent).not.toContain("높이 (m) · 1:1");
    fireEvent.click(screen.getByRole("button", { name: "1:1" }));
    expect(container.textContent).toContain("높이 (m) · 1:1");
    expect(screen.getByRole("button", { name: "1:1" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("권한이 없어 숨긴 날짜는 이유를 알리고 남은 날짜만 그린다", () => {
    const { container } = render(<MeasurementWorkbench {...props({
      current: null,
      unavailable: [{ role: "cur", label: "2026-11-02", message: "접근 권한이 없어 표시하지 않습니다." }],
    })} />);
    expect(screen.getByRole("alert").textContent).toContain("접근 권한이 없어 표시하지 않습니다.");
    expect(container.querySelector('[data-series="cur"]')).toBeNull();
    expect(container.querySelector('[data-series="ref"]')).not.toBeNull();
  });

  it("날짜는 서버로 다시 요청한다(고르기만으로 새 계산을 만들지 않는다)", () => {
    const { container } = render(<MeasurementWorkbench {...props()} />);
    const form = container.querySelector("form")!;
    expect(form.method).toBe("get");
    expect(Array.from(form.querySelectorAll("select")).map((select) => select.name).sort()).toEqual(["cur", "ref"]);
    expect(form.querySelector('input[name="workAreaId"]')!.getAttribute("value")).toBe("area-1");
  });

  it("측정 선이 둘 이상이면 고르는 목록이 생긴다", () => {
    const other = `mf-${"2".repeat(32)}`;
    const { container } = render(<MeasurementWorkbench {...props({ features: [
      { featureId: FEATURE_ID, label: "북쪽 경사면 · 개정 2" }, { featureId: other, label: "동쪽 경계선 · 개정 1" },
    ] })} />);
    expect(container.querySelector('select[name="feature"]')).not.toBeNull();
  });

  it("거리별 값 표는 값 없는 지점의 이유를 적는다", () => {
    render(<MeasurementWorkbench {...props()} />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByText(/값 없음 · 자료 없음/).length).toBeGreaterThanOrEqual(2);
  });

  describe("CSV 내보내기", () => {
    it("보이는 두 날짜를 모르는 지점의 이유와 함께 내려받는다", async () => {
      let blob: Blob | null = null;
      const originalCreate = URL.createObjectURL;
      URL.createObjectURL = vi.fn((value: Blob) => { blob = value; return "blob:test"; });
      URL.revokeObjectURL = vi.fn();
      const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
      try {
        const input = props();
        const read = mockFreshDateResults(input);
        render(<MeasurementWorkbench {...input} />);
        fireEvent.click(screen.getByRole("button", { name: "날짜별 높이 CSV 내보내기" }));
        await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
        expect(read).toHaveBeenCalledTimes(2);
        const text = await new Promise<string>((resolve) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob!); });
        const lines = text.replace(/^﻿/, "").trim().split("\r\n");
        expect(lines[0]).toBe("series,distance_m,x,y,elevation_m,unknown_reason,vertical_reference");
        expect(lines).toHaveLength(1 + 10);
        expect(lines.filter((line) => line.startsWith('"기준 2026-03-14"'))).toHaveLength(5);
        expect(lines.filter((line) => line.startsWith('"현재 2026-11-02"'))).toHaveLength(5);
        const unknown = lines.filter((line) => line.includes(",NODATA,"));
        expect(unknown).toHaveLength(2);
        // 모르는 지점의 높이 칸은 비어 있다.
        expect(unknown.every((line) => /,,NODATA,/.test(line))).toBe(true);
      } finally {
        URL.createObjectURL = originalCreate;
      }
    });
    it("한 날짜의 읽기 권한이 철회되면 날짜별 CSV 전체를 닫는다", async () => {
      const input = props();
      mockFreshDateResults(input, input.curJobId!);
      const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
      render(<MeasurementWorkbench {...input} />);
      fireEvent.click(screen.getByRole("button", { name: "날짜별 높이 CSV 내보내기" }));
      expect((await screen.findByRole("alert")).textContent).toContain("접근 권한");
      expect(click).not.toHaveBeenCalled();
    });
  });
});

describe("수직 기준 출처", () => {
  const observed = { provenance: "OBSERVED", observed: { identifier: "EPSG:5773", basis: "EGM96 height" }, declared: null } as const;
  const declared = (datum: "orthometric_kngeoid2018" | "ellipsoidal" = "orthometric_kngeoid2018") => ({
    provenance: "DECLARED", observed: null,
    declared: { declarationId: `vrd-${"1".repeat(32)}`, declarationDigest: DIGEST, datum, unit: "metre", basis: "Terra에서 내보냄", declaredBy: "operator-1", declaredAt: "2026-11-17T00:00:00Z" },
  }) as const;
  const withVertical = (ref: WorkbenchProps["baseline"] extends infer T ? T : never, cur: WorkbenchProps["current"]) => props({ baseline: ref, current: cur });
  const series = (jobId: string, label: string, offset: number, vertical: unknown) => ({ jobId, label, result: result(offset), vertical }) as NonNullable<WorkbenchProps["baseline"]>;

  it("파일에서 확인한 기준은 그렇게 말하고 선언 안내를 띄우지 않는다", () => {
    render(<MeasurementWorkbench {...withVertical(series(`spj-${"1".repeat(32)}`, "2026-03-14", 0, observed), series(`spj-${"3".repeat(32)}`, "2026-11-02", 0.8, observed))} />);
    const facts = screen.getByRole("complementary").querySelector("dl")!;
    expect(facts.textContent).toContain("기준 파일에서 확인 · EPSG:5773");
    expect(facts.textContent).not.toContain("선언");
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("선언한 기준은 선언이라고 말하고, 확인되지 않았음을 그래프 위에서 먼저 알린다", () => {
    render(<MeasurementWorkbench {...withVertical(series(`spj-${"1".repeat(32)}`, "2026-03-14", 0, declared()), series(`spj-${"3".repeat(32)}`, "2026-11-02", 0.8, declared()))} />);
    const facts = screen.getByRole("complementary").querySelector("dl")!;
    expect(facts.textContent).toContain("기준 사용자 선언 · 정표고(KNGeoid2018)");
    expect(facts.textContent).toContain("파일에서 확인되지 않은 선언값");
    const notes = screen.getAllByRole("note").map((node) => node.textContent ?? "");
    expect(notes).toHaveLength(1);
    expect(notes[0]).toContain("사용자가 선언한 값이며 파일에서 확인되지 않았습니다");
    expect(notes[0]).toContain("검증하지 않습니다");
    expect(notes[0]).not.toContain("정확");
  });

  it("두 날짜의 수직 기준이 다르면 높이를 빼어 읽지 말라고 알린다", () => {
    render(<MeasurementWorkbench {...withVertical(series(`spj-${"1".repeat(32)}`, "2026-03-14", 0, observed), series(`spj-${"3".repeat(32)}`, "2026-11-02", 0.8, declared()))} />);
    const notes = screen.getAllByRole("note").map((node) => node.textContent ?? "");
    expect(notes.some((text) => text.includes("수직 기준이 달라"))).toBe(true);
    // 같은 선언이면 경고하지 않는다.
    cleanup();
    render(<MeasurementWorkbench {...withVertical(series(`spj-${"1".repeat(32)}`, "2026-03-14", 0, declared()), series(`spj-${"3".repeat(32)}`, "2026-11-02", 0.8, declared()))} />);
    expect(screen.getAllByRole("note").some((node) => (node.textContent ?? "").includes("수직 기준이 달라"))).toBe(false);
    cleanup();
    render(<MeasurementWorkbench {...withVertical(series(`spj-${"1".repeat(32)}`, "2026-03-14", 0, declared("ellipsoidal")), series(`spj-${"3".repeat(32)}`, "2026-11-02", 0.8, declared("orthometric_kngeoid2018")))} />);
    expect(screen.getAllByRole("note").some((node) => (node.textContent ?? "").includes("수직 기준이 달라"))).toBe(true);
  });

  it("출처를 모르면 모른다고 쓰고 비교해도 된다고 말하지 않는다", () => {
    render(<MeasurementWorkbench {...props()} />);
    const facts = screen.getByRole("complementary").querySelector("dl")!;
    expect(facts.textContent).toContain("수직 기준 확인 불가");
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("CSV 행마다 수직 기준 출처를 싣는다", async () => {
    let blob: Blob | null = null;
    URL.createObjectURL = vi.fn((value: Blob) => { blob = value; return "blob:test"; });
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const input = withVertical(series(`spj-${"1".repeat(32)}`, "2026-03-14", 0, observed), series(`spj-${"3".repeat(32)}`, "2026-11-02", 0.8, declared()));
    mockFreshDateResults(input);
    render(<MeasurementWorkbench {...input} />);
    fireEvent.click(screen.getByRole("button", { name: "날짜별 높이 CSV 내보내기" }));
    await waitFor(() => expect(blob).not.toBeNull());
    const text = await new Promise<string>((resolve) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob!); });
    const lines = text.replace(/^﻿/, "").trim().split("\r\n").slice(1);
    expect(lines.filter((line) => line.startsWith('"기준 ') && line.endsWith(',"observed:EPSG:5773"'))).toHaveLength(5);
    expect(lines.filter((line) => line.startsWith('"현재 ') && line.endsWith(',"declared:orthometric_kngeoid2018"'))).toHaveLength(5);
  });
});
