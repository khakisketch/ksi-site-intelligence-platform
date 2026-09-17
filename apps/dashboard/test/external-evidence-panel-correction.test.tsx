// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExternalEvidencePanel } from "@/app/field/ExternalEvidencePanel";

const ref = (character: string) => `ers-v1-${character.repeat(64)}`;
const current = {
  submissionRef: ref("a"),
  state: "SEALED" as const,
  submission: {
    revision: 1,
    artifacts: [{ artifactId: "dsm", kind: "dsm", fileName: "current.tif" }],
  },
};
const sameWorkOrderBaseline = {
  submissionRef: ref("b"),
  state: "SEALED" as const,
  submission: {
    revision: 2,
    artifacts: [{ artifactId: "dsm", kind: "dsm", fileName: "same-work-order.tif" }],
  },
};
const otherWorkOrderBaseline = {
  submissionRef: ref("c"),
  state: "SEALED" as const,
  submission: {
    revision: 1,
    artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "other-work-order.tif" }],
  },
};
const orthoOnly = {
  submissionRef: ref("d"),
  state: "SEALED" as const,
  submission: {
    revision: 1,
    artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho-only.tif" }],
  },
};
const fetchMock = vi.fn();

function response(value: unknown) {
  return { ok: true, json: async () => value };
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith("/evidence")) {
      return response({
        items: [{
          evidenceRef: `eev-v1-${"e".repeat(64)}`,
          state: "SEALED_BYTE_OBSERVED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"f".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "현장 재구성과 독립된 측량",
          measurementSummaries: [{
            coreVerdict: "VALIDATED",
            measuredCheckpointCount: 3,
            meanErrorM: -0.02,
            maeM: 0.04,
            rmseM: 0.05,
            recordedAt: "2026-09-09T00:00:00Z",
          }],
        }],
      });
    }
    if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
    if (url === "/api/sites/site-1/observation-work-orders") {
      return response({ workOrders: [{ workOrderId: "current", name: "현재 작업", cycleNumber: 1 }] });
    }
    if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") {
      return response({ submissions: [current] });
    }
    throw new Error(`unexpected fetch ${url}`);
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("renders only the Core-recorded checkpoint aggregate and labels independence as a declaration", async () => {
  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite={false} />);

  expect(await screen.findByText("Core 측정 집계")).toBeTruthy();
  expect(screen.getByText("검사점 3개 · 평균 오차 -0.02m · MAE 0.04m · RMSE 0.05m")).toBeTruthy();
  expect(screen.getByText("Core 기록 시각: 2026-09-09T00:00:00Z")).toBeTruthy();
  expect(screen.getByText("독립성 근거 선언: 현장 재구성과 독립된 측량")).toBeTruthy();
  expect(screen.getByText("이 선언은 Core가 독립성을 증명한 사실이 아닙니다.")).toBeTruthy();
});

it("keeps sealed ortho-only display subjects visible while distinguishing an aggregate wait from an evidence read failure", async () => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.includes(orthoOnly.submissionRef) && url.endsWith("/evidence")) throw new Error("read failed");
    if (url.endsWith("/evidence")) {
      return response({
        items: [{
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "SEALED_BYTE_OBSERVED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"b".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "독립 측량",
        }],
      });
    }
    if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
    if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, orthoOnly]} canWrite={false} />);

  expect(await screen.findByText("Core 측정 집계 대기")).toBeTruthy();
  expect(screen.getByText("DSM 없음: 표시는 가능하지만 독립 검사점·높이·상대 물량은 제한됩니다.")).toBeTruthy();
  expect((await screen.findByRole("alert")).textContent).toContain("독립 검사점 증거를 읽지 못했습니다.");
});

it("keeps evidence readable but blocks new evidence and use decisions after closure", async () => {
  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite newIntentAllowed={false} />);

  expect(await screen.findByText(/업무 종료 상태입니다. 새 증거와 사용 결정은 요청할 수 없지만/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /current\.tif/ }));
  expect((screen.getByRole("button", { name: "표시 결정 다시 평가" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(true);
});

it("keeps same-work-order and cross-work-order baselines human-readable, sends an active zone only for volume, and retains each use receipt", async () => {
  const pairBodies: Record<string, unknown>[] = [];
  const onRelativeVolumeDecisionChange = vi.fn();
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/evidence")) return response({ items: [] });
    if (url === "/api/sites/site-1/work-areas") {
      return response({ workAreas: [{ workAreaId: "area-1", name: "A구역", status: "ACTIVE" }] });
    }
    if (url === "/api/sites/site-1/observation-work-orders") {
      return response({
        workOrders: [
          { workOrderId: "current", name: "현재 작업", cycleNumber: 1 },
          { workOrderId: "other", name: "기준 작업", cycleNumber: 2 },
        ],
      });
    }
    if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") {
      return response({ submissions: [current, sameWorkOrderBaseline] });
    }
    if (url === "/api/observation-work-orders/other/external-reconstruction-submissions") {
      return response({ submissions: [otherWorkOrderBaseline] });
    }
    if (url.endsWith("/single")) {
      const use = JSON.parse(String(init?.body)).use as string;
      return response({ decision: { decisionId: `external-use-decision-${use[0].repeat(32)}`, use, verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
    }
    if (url.endsWith("/pair")) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      pairBodies.push(body);
      return response({ decision: { decisionId: `external-use-decision-${String(body.use)[0].repeat(32)}`, decisionDigest: `sha256:${String(body.use)[0].repeat(64)}`, use: body.use, verdict: "RESTRICTED", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite onRelativeVolumeDecisionChange={onRelativeVolumeDecisionChange} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  await waitFor(() => expect(screen.getByLabelText("비교 기준 봉인 재구성").querySelectorAll("option")).toHaveLength(3));
  const options = [...screen.getByLabelText("비교 기준 봉인 재구성").querySelectorAll("option")];
  expect(options.map((option) => option.textContent).join(" ")).not.toContain("ers-v1-");
  expect(options.map((option) => option.textContent).join(" ")).toContain("same-work-order.tif");
  expect(options.map((option) => option.textContent).join(" ")).toContain("other-work-order.tif");

  fireEvent.change(screen.getByLabelText("비교 기준 봉인 재구성"), {
    target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` },
  });
  fireEvent.change(screen.getByLabelText("상대 물량 작업구역"), { target: { value: "area-1" } });
  fireEvent.click(screen.getByRole("button", { name: "표시 결정 다시 평가" }));
  expect(await screen.findByText(/현재 Core 결정: DISPLAY/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "높이 결정 다시 평가" }));
  expect(await screen.findByText(/현재 Core 결정: HEIGHT/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "시각 비교 결정 다시 평가" }));
  expect(await screen.findByText(/현재 Core 결정: VISUAL_COMPARISON/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "상대 물량 결정 다시 평가" }));
  expect(await screen.findByText(/현재 Core 결정: RELATIVE_VOLUME/)).toBeTruthy();

  expect(screen.getByText(/현재 Core 결정: DISPLAY/)).toBeTruthy();
  expect(screen.getByText(/현재 Core 결정: HEIGHT/)).toBeTruthy();
  expect(pairBodies).toEqual([
    {
      use: "VISUAL_COMPARISON",
      baselineWorkOrderId: "current",
      baselineSubmissionRef: sameWorkOrderBaseline.submissionRef,
      baselineRevision: 2,
    },
    {
      use: "RELATIVE_VOLUME",
      baselineWorkOrderId: "current",
      baselineSubmissionRef: sameWorkOrderBaseline.submissionRef,
      baselineRevision: 2,
      zoneId: "area-1",
    },
  ]);
  expect(onRelativeVolumeDecisionChange).toHaveBeenLastCalledWith(expect.objectContaining({
    decisionId: `external-use-decision-${"R".repeat(32)}`,
    decisionDigest: `sha256:${"R".repeat(64)}`,
    verdict: "RESTRICTED",
  }));
});

it("reuses an uncertain decision key and never publishes its late response after subject selection changes", async () => {
  const next = {
    submissionRef: ref("e"),
    state: "SEALED" as const,
    submission: { revision: 1, artifacts: [{ artifactId: "dsm", kind: "dsm", fileName: "next.tif" }] },
  };
  let displayAttempts = 0;
  let oldSignal: AbortSignal | undefined;
  let resolveLate: ((value: unknown) => void) | undefined;
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith("/evidence")) return Promise.resolve(response({ items: [] }));
    if (url === "/api/sites/site-1/work-areas") return Promise.resolve(response({ workAreas: [] }));
    if (url === "/api/sites/site-1/observation-work-orders") return Promise.resolve(response({ workOrders: [] }));
    if (url.endsWith("/single")) {
      displayAttempts += 1;
      if (displayAttempts === 1) return Promise.resolve({ ok: false, json: async () => ({}) });
      if (displayAttempts === 2) {
        oldSignal = init?.signal ?? undefined;
        return new Promise((resolve) => { resolveLate = resolve; });
      }
      if (displayAttempts === 3) {
        return Promise.resolve(response({ decision: { decisionId: `external-use-decision-${"d".repeat(32)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } }));
      }
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, next]} canWrite />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.click(screen.getByRole("button", { name: "표시 결정 다시 평가" }));
  expect(await screen.findByText("DISPLAY Core 결정을 읽지 못했습니다.")).toBeTruthy();
  const firstHeader = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/single"))?.[1] as RequestInit;
  fireEvent.click(screen.getByRole("button", { name: "표시 결정 다시 평가" }));
  await waitFor(() => expect(oldSignal).toBeDefined());
  const secondHeader = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/single"))[1]?.[1] as RequestInit;
  expect((firstHeader.headers as Record<string, string>)["idempotency-key"]).toBe((secondHeader.headers as Record<string, string>)["idempotency-key"]);

  fireEvent.click(screen.getByRole("button", { name: /next\.tif/ }));
  expect(oldSignal?.aborted).toBe(true);
  resolveLate?.(response({ decision: { decisionId: `external-use-decision-${"f".repeat(32)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } }));
  await waitFor(() => expect(screen.queryByText(/현재 Core 결정: DISPLAY/)).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "표시 결정 다시 평가" }));
  await waitFor(() => expect(displayAttempts).toBe(3));
});

it("converges a lost successful seal response with the frozen CSV declaration and no second grant or upload", async () => {
  vi.stubGlobal("crypto", {
    randomUUID: () => "stable-key",
    subtle: { digest: async () => new Uint8Array(32).buffer },
  });
  const declarationBodies: Record<string, unknown>[] = [];
  const declarationKeys: string[] = [];
  let grantCalls = 0;
  let uploadCalls = 0;
  let evidenceReads = 0;
  const evidenceItem = (state: "DECLARED" | "SEALED_BYTE_OBSERVED") => ({
    evidenceRef: `eev-v1-${"a".repeat(64)}`,
    state,
    targetDsmArtifactId: "dsm",
    declaredContentDigest: `sha256:${"0".repeat(64)}`,
    declaredContentType: "text/csv",
    independenceBasis: "독립 측량",
  });
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/evidence") && !init?.method) {
      evidenceReads += 1;
      return response({ items: [] });
    }
    if (url.endsWith("/evidence") && init?.method === "POST") {
      declarationBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>);
      declarationKeys.push((init.headers as Record<string, string>)["idempotency-key"]);
      return response(evidenceItem(declarationBodies.length === 1 ? "DECLARED" : "SEALED_BYTE_OBSERVED"));
    }
    if (url.endsWith("/upload-grant")) {
      grantCalls += 1;
      return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, uploadUrl: "https://upload.test/checkpoints", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
    }
    if (url === "https://upload.test/checkpoints") {
      uploadCalls += 1;
      return response({});
    }
    if (url.endsWith("/seal")) return { ok: false, json: async () => ({}) };
    if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
    if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
    throw new Error(`unexpected fetch ${url}`);
  });
  const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
  Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
  fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
  fireEvent.click(screen.getByRole("button", { name: "CSV 선언·업로드·봉인" }));
  expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "CSV 선언·업로드·봉인" }));

  expect(await screen.findByText("Core가 동일 CSV 바이트를 이미 봉인했습니다.")).toBeTruthy();
  expect(declarationBodies).toEqual([
    {
      targetDsmArtifactId: "dsm",
      declaredContentDigest: `sha256:${"0".repeat(64)}`,
      declaredContentType: "text/csv",
      independenceBasis: "독립 측량",
    },
    {
      targetDsmArtifactId: "dsm",
      declaredContentDigest: `sha256:${"0".repeat(64)}`,
      declaredContentType: "text/csv",
      independenceBasis: "독립 측량",
    },
  ]);
  expect(declarationKeys[0]).toBe(declarationKeys[1]);
  expect(grantCalls).toBe(1);
  expect(uploadCalls).toBe(1);
  expect(evidenceReads).toBeGreaterThanOrEqual(2);
});

it("shows every immutable single-subject Core binding to a read-only user without turning it into current authority", async () => {
  const historicalId = `external-use-decision-${"a".repeat(32)}`;
  const historicalDecision = {
    contractVersion: "external-use-decision-v1",
    decisionId: historicalId,
    decisionDigest: `sha256:${"b".repeat(64)}`,
    use: "DISPLAY",
    verdict: "ELIGIBLE",
    reasons: ["HISTORICAL"],
    remediations: [],
    decidedAt: "2026-09-08T00:00:00Z",
    subject: {
      organizationId: "org-1",
      siteId: "site-1",
      workOrderId: "current",
      submissionId: current.submissionRef,
      revision: 1,
      submissionDigest: `sha256:${"c".repeat(64)}`,
      manifestDigest: `sha256:${"d".repeat(64)}`,
    },
    subjectDigest: `sha256:${"e".repeat(64)}`,
    policyDigest: `sha256:${"f".repeat(64)}`,
    inspectionReportDigest: `sha256:${"1".repeat(64)}`,
    evidenceRecordDigests: [`sha256:${"2".repeat(64)}`, `sha256:${"3".repeat(64)}`],
    sanitizedDisplayReceiptDigest: `sha256:${"4".repeat(64)}`,
  };
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith("/evidence")) return response({ items: [] });
    if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
    if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
    if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") return response({ submissions: [current] });
    if (url.endsWith(`/${historicalId}`)) {
      return response({ decision: historicalDecision });
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite={false} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.change(screen.getByLabelText("과거 Core 결정 참조"), { target: { value: historicalId } });
  fireEvent.click(screen.getByRole("button", { name: "과거 결정 조회" }));

  expect(await screen.findByText(/과거 불변 Core 결정: DISPLAY/)).toBeTruthy();
  expect(screen.getByText(`결정 ID: ${historicalId}`)).toBeTruthy();
  expect(screen.getByText(`결정 다이제스트: ${historicalDecision.decisionDigest}`)).toBeTruthy();
  expect(screen.getByText("대상: 조직 org-1 · 현장 site-1 · 작업 current")).toBeTruthy();
  expect(screen.getByText(`제출 ${current.submissionRef} · rev 1 · 제출 다이제스트 ${historicalDecision.subject.submissionDigest}`)).toBeTruthy();
  expect(screen.getByText(`매니페스트 다이제스트 ${historicalDecision.subject.manifestDigest} · 대상 다이제스트 ${historicalDecision.subjectDigest}`)).toBeTruthy();
  expect(screen.getByText(`정책 다이제스트: ${historicalDecision.policyDigest}`)).toBeTruthy();
  expect(screen.getByText(`검사 보고서 다이제스트: ${historicalDecision.inspectionReportDigest}`)).toBeTruthy();
  expect(screen.getByText(`증거 기록 다이제스트: ${historicalDecision.evidenceRecordDigests.join(", ")}`)).toBeTruthy();
  expect(screen.getByText(`표시 영수증 다이제스트: ${historicalDecision.sanitizedDisplayReceiptDigest}`)).toBeTruthy();
  expect(screen.getByText("과거 기록은 현재 사용 권한이나 실행 권한이 아닙니다.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "표시 결정 다시 평가" })).toBeNull();
});

it("shows the ordered pair and zone bindings returned by an immutable historical Core decision", async () => {
  const historicalId = `external-use-decision-${"b".repeat(32)}`;
  const baseline = {
    organizationId: "org-1",
    siteId: "site-1",
    workOrderId: "baseline-work-order",
    submissionId: sameWorkOrderBaseline.submissionRef,
    revision: 2,
    submissionDigest: `sha256:${"5".repeat(64)}`,
    manifestDigest: `sha256:${"6".repeat(64)}`,
  };
  const currentSubject = {
    organizationId: "org-1",
    siteId: "site-1",
    workOrderId: "current",
    submissionId: current.submissionRef,
    revision: 1,
    submissionDigest: `sha256:${"7".repeat(64)}`,
    manifestDigest: `sha256:${"8".repeat(64)}`,
  };
  const pairDecision = {
    contractVersion: "external-pair-use-decision-v1",
    decisionId: historicalId,
    decisionDigest: `sha256:${"9".repeat(64)}`,
    use: "RELATIVE_VOLUME",
    verdict: "RESTRICTED",
    reasons: ["HISTORICAL_PAIR"],
    remediations: ["REMEASURE"],
    decidedAt: "2026-09-08T00:00:00Z",
    baselineSubject: baseline,
    baselineSubjectDigest: `sha256:${"a".repeat(64)}`,
    currentSubject,
    currentSubjectDigest: `sha256:${"b".repeat(64)}`,
    policyDigest: `sha256:${"c".repeat(64)}`,
    baselineInspectionReportDigest: `sha256:${"d".repeat(64)}`,
    currentInspectionReportDigest: `sha256:${"e".repeat(64)}`,
    evidenceRecordDigests: [`sha256:${"f".repeat(64)}`],
    baselineSanitizedDisplayReceiptDigest: `sha256:${"0".repeat(64)}`,
    currentSanitizedDisplayReceiptDigest: `sha256:${"1".repeat(64)}`,
    zone: {
      zoneId: "area-1",
      revision: 3,
      definitionDigest: `sha256:${"2".repeat(64)}`,
      observedCrsDigest: `sha256:${"3".repeat(64)}`,
      observedVerticalReferenceDigest: `sha256:${"4".repeat(64)}`,
    },
    compatibilityMappingDigest: `sha256:${"5".repeat(64)}`,
  };
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith("/evidence")) return response({ items: [] });
    if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
    if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
    if (url.endsWith(`/${historicalId}`)) return response({ decision: pairDecision });
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite={false} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.change(screen.getByLabelText("과거 Core 결정 참조"), { target: { value: historicalId } });
  fireEvent.click(screen.getByRole("button", { name: "과거 결정 조회" }));

  expect(await screen.findByText(/과거 불변 Core 결정: RELATIVE_VOLUME/)).toBeTruthy();
  expect(screen.getByText(`결정 ID: ${historicalId}`)).toBeTruthy();
  expect(screen.getByText(`결정 다이제스트: ${pairDecision.decisionDigest}`)).toBeTruthy();
  expect(screen.getByText("계약 버전: external-pair-use-decision-v1")).toBeTruthy();
  expect(screen.getByText("순서 있는 기준 대상: 조직 org-1 · 현장 site-1 · 작업 baseline-work-order")).toBeTruthy();
  expect(screen.getByText(`제출 ${sameWorkOrderBaseline.submissionRef} · rev 2 · 제출 다이제스트 ${baseline.submissionDigest}`)).toBeTruthy();
  expect(screen.getByText(`매니페스트 다이제스트 ${baseline.manifestDigest} · 대상 다이제스트 ${pairDecision.baselineSubjectDigest}`)).toBeTruthy();
  expect(screen.getByText("순서 있는 현재 대상: 조직 org-1 · 현장 site-1 · 작업 current")).toBeTruthy();
  expect(screen.getByText(`제출 ${current.submissionRef} · rev 1 · 제출 다이제스트 ${currentSubject.submissionDigest}`)).toBeTruthy();
  expect(screen.getByText(`매니페스트 다이제스트 ${currentSubject.manifestDigest} · 대상 다이제스트 ${pairDecision.currentSubjectDigest}`)).toBeTruthy();
  expect(screen.getByText(`정책 다이제스트: ${pairDecision.policyDigest}`)).toBeTruthy();
  expect(screen.getByText(`기준 검사 보고서 다이제스트: ${pairDecision.baselineInspectionReportDigest}`)).toBeTruthy();
  expect(screen.getByText(`현재 검사 보고서 다이제스트: ${pairDecision.currentInspectionReportDigest}`)).toBeTruthy();
  expect(screen.getByText(`증거 기록 다이제스트: ${pairDecision.evidenceRecordDigests.join(", ")}`)).toBeTruthy();
  expect(screen.getByText(`기준 표시 영수증 다이제스트: ${pairDecision.baselineSanitizedDisplayReceiptDigest}`)).toBeTruthy();
  expect(screen.getByText(`현재 표시 영수증 다이제스트: ${pairDecision.currentSanitizedDisplayReceiptDigest}`)).toBeTruthy();
  expect(screen.getByText("봉인 작업구역: area-1 · rev 3")).toBeTruthy();
  expect(screen.getByText(`작업구역 정의 다이제스트: ${pairDecision.zone.definitionDigest}`)).toBeTruthy();
  expect(screen.getByText(`관측 좌표계 다이제스트: ${pairDecision.zone.observedCrsDigest}`)).toBeTruthy();
  expect(screen.getByText(`관측 수직 기준 다이제스트: ${pairDecision.zone.observedVerticalReferenceDigest}`)).toBeTruthy();
  expect(screen.getByText(`호환성 매핑 다이제스트: ${pairDecision.compatibilityMappingDigest}`)).toBeTruthy();
});

it("names incomplete same-site baselines and retries every exact choice after a partial fetch failure", async () => {
  let recovered = false;
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith("/evidence")) return response({ items: [] });
    if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
    if (url === "/api/sites/site-1/observation-work-orders") {
      return response({
        workOrders: [
          { workOrderId: "current", name: "현재 작업" },
          { workOrderId: "healthy", name: "정상 기준" },
          { workOrderId: "incomplete", name: "누락 기준" },
        ],
      });
    }
    if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") return response({ submissions: [current] });
    if (url === "/api/observation-work-orders/healthy/external-reconstruction-submissions") return response({ submissions: [sameWorkOrderBaseline] });
    if (url === "/api/observation-work-orders/incomplete/external-reconstruction-submissions") {
      return recovered ? response({ submissions: [otherWorkOrderBaseline] }) : { ok: false, json: async () => ({}) };
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  expect((await screen.findByRole("alert")).textContent).toContain("일부 같은 현장 작업의 비교 기준을 읽지 못했습니다: 누락 기준. 목록이 완전하지 않습니다.");
  expect(screen.getByLabelText("비교 기준 봉인 재구성").querySelectorAll("option")).toHaveLength(2);

  recovered = true;
  fireEvent.click(screen.getByRole("button", { name: "비교 기준 다시 시도" }));
  await waitFor(() => expect(screen.getByLabelText("비교 기준 봉인 재구성").querySelectorAll("option")).toHaveLength(3));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("retires a pending pair request for baseline and zone changes so each next scoped request runs", async () => {
  const secondBaseline = {
    submissionRef: ref("e"),
    state: "SEALED" as const,
    submission: { revision: 1, artifacts: [{ artifactId: "dsm-2", kind: "dsm", fileName: "second-baseline.tif" }] },
  };
  let pairAttempts = 0;
  const signals: AbortSignal[] = [];
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith("/evidence")) return Promise.resolve(response({ items: [] }));
    if (url === "/api/sites/site-1/work-areas") {
      return Promise.resolve(response({ workAreas: [
        { workAreaId: "area-a", name: "A구역", status: "ACTIVE" },
        { workAreaId: "area-b", name: "B구역", status: "ACTIVE" },
      ] }));
    }
    if (url === "/api/sites/site-1/observation-work-orders") return Promise.resolve(response({ workOrders: [{ workOrderId: "current", name: "현재 작업" }] }));
    if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") return Promise.resolve(response({ submissions: [current, sameWorkOrderBaseline, secondBaseline] }));
    if (url.endsWith("/pair")) {
      pairAttempts += 1;
      if (pairAttempts === 1 || pairAttempts === 3) {
        signals.push(init?.signal as AbortSignal);
        return new Promise(() => undefined);
      }
      const body = JSON.parse(String(init?.body)) as { use: string };
      return Promise.resolve(response({ decision: { decisionId: `external-use-decision-${String(pairAttempts).repeat(32)}`, use: body.use, verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } }));
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  await waitFor(() => expect(screen.getByLabelText("비교 기준 봉인 재구성").querySelectorAll("option")).toHaveLength(3));
  fireEvent.change(screen.getByLabelText("비교 기준 봉인 재구성"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
  fireEvent.change(screen.getByLabelText("상대 물량 작업구역"), { target: { value: "area-a" } });
  fireEvent.click(screen.getByRole("button", { name: "시각 비교 결정 다시 평가" }));
  await waitFor(() => expect(pairAttempts).toBe(1));

  fireEvent.change(screen.getByLabelText("비교 기준 봉인 재구성"), { target: { value: `current:${secondBaseline.submissionRef}:1` } });
  expect(signals[0].aborted).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "시각 비교 결정 다시 평가" }));
  await waitFor(() => expect(pairAttempts).toBe(2));

  fireEvent.click(screen.getByRole("button", { name: "상대 물량 결정 다시 평가" }));
  await waitFor(() => expect(pairAttempts).toBe(3));
  fireEvent.change(screen.getByLabelText("상대 물량 작업구역"), { target: { value: "area-b" } });
  expect(signals[1].aborted).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "상대 물량 결정 다시 평가" }));
  await waitFor(() => expect(pairAttempts).toBe(4));
});

it("retires a pending evidence operation when the target changes so the next target decision runs", async () => {
  vi.stubGlobal("crypto", {
    randomUUID: () => "stable-key",
    subtle: { digest: async () => new Uint8Array(32).buffer },
  });
  const next = {
    submissionRef: ref("f"),
    state: "SEALED" as const,
    submission: { revision: 1, artifacts: [{ artifactId: "next-dsm", kind: "dsm", fileName: "next.tif" }] },
  };
  let evidenceSignal: AbortSignal | undefined;
  let displayAttempts = 0;
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith("/evidence") && !init?.method) return Promise.resolve(response({ items: [] }));
    if (url.endsWith("/evidence") && init?.method === "POST") {
      evidenceSignal = init.signal ?? undefined;
      return new Promise(() => undefined);
    }
    if (url === "/api/sites/site-1/work-areas") return Promise.resolve(response({ workAreas: [] }));
    if (url === "/api/sites/site-1/observation-work-orders") return Promise.resolve(response({ workOrders: [] }));
    if (url.endsWith("/single")) {
      displayAttempts += 1;
      return Promise.resolve(response({ decision: { decisionId: `external-use-decision-${"f".repeat(32)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } }));
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
  Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, next]} canWrite />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
  fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
  fireEvent.click(screen.getByRole("button", { name: "CSV 선언·업로드·봉인" }));
  await waitFor(() => expect(evidenceSignal).toBeDefined());

  fireEvent.click(screen.getByRole("button", { name: /next\.tif/ }));
  expect(evidenceSignal?.aborted).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "표시 결정 다시 평가" }));
  await waitFor(() => expect(displayAttempts).toBe(1));
});

describe("SINGLE_VOLUME decision", () => {
  const singleVolumeFetch = (outcomes: Array<"fail" | "eligible" | "blocked">, bodies: unknown[], keys: string[]) =>
    async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence")) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") {
        return response({ workAreas: [{ workAreaId: "pile-1", name: "야적장 1", status: "ACTIVE" }] });
      }
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/use-decisions/single-volume")) {
        bodies.push(JSON.parse(String(init?.body)));
        keys.push((init?.headers as Record<string, string>)["idempotency-key"]);
        const outcome = outcomes[bodies.length - 1];
        if (outcome === "fail") return { ok: false, json: async () => ({}) };
        return response({
          decision: {
            decisionId: `external-use-decision-${"5".repeat(32)}`,
            decisionDigest: `sha256:${"5".repeat(64)}`,
            use: "SINGLE_VOLUME",
            verdict: outcome === "blocked" ? "BLOCKED" : "ELIGIBLE",
            reasons: outcome === "blocked" ? ["SINGLE_VOLUME_MAPPING_UNAVAILABLE"] : [],
            remediations: outcome === "blocked" ? ["AUTHORIZE_SINGLE_VOLUME_MAPPING"] : [],
            decidedAt: "2026-09-17T00:00:00Z",
          },
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    };

  it("requires a WorkArea but no baseline, posts only the zone to the single-volume route and reuses the key on retry", async () => {
    const bodies: unknown[] = [];
    const keys: string[] = [];
    let counter = 0;
    vi.stubGlobal("crypto", { randomUUID: () => `key-${(counter += 1)}` });
    fetchMock.mockImplementation(singleVolumeFetch(["fail", "eligible"], bodies, keys));
    const onSingleVolumeDecisionChange = vi.fn();
    const onRelativeVolumeDecisionChange = vi.fn();

    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite onSingleVolumeDecisionChange={onSingleVolumeDecisionChange} onRelativeVolumeDecisionChange={onRelativeVolumeDecisionChange} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("단일 시점 체적 작업구역").querySelectorAll("option")).toHaveLength(2));

    fireEvent.click(screen.getByRole("button", { name: "단일 시점 체적 결정 다시 평가" }));
    expect(await screen.findByText("단일 시점 체적 작업구역을 선택하세요.")).toBeTruthy();
    expect(bodies).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("단일 시점 체적 작업구역"), { target: { value: "pile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "단일 시점 체적 결정 다시 평가" }));
    expect(await screen.findByText("SINGLE_VOLUME Core 결정을 읽지 못했습니다.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "단일 시점 체적 결정 다시 평가" }));
    expect(await screen.findByText(/현재 Core 결정: SINGLE_VOLUME · ELIGIBLE/)).toBeTruthy();

    expect(bodies).toEqual([{ zoneId: "pile-1" }, { zoneId: "pile-1" }]);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/pair"))).toBe(false);
    expect((screen.getByLabelText("비교 기준 봉인 재구성") as HTMLSelectElement).value).toBe("");
    expect(onSingleVolumeDecisionChange).toHaveBeenLastCalledWith(expect.objectContaining({
      decisionId: `external-use-decision-${"5".repeat(32)}`,
      verdict: "ELIGIBLE",
    }));
    expect(onRelativeVolumeDecisionChange).not.toHaveBeenCalledWith(expect.objectContaining({ use: "SINGLE_VOLUME" }));
  });

  it("refuses a single-volume decision for a revision without DSM", async () => {
    const bodies: unknown[] = [];
    fetchMock.mockImplementation(singleVolumeFetch(["eligible"], bodies, []));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[orthoOnly]} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: /ortho-only\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("단일 시점 체적 작업구역").querySelectorAll("option")).toHaveLength(2));
    fireEvent.change(screen.getByLabelText("단일 시점 체적 작업구역"), { target: { value: "pile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "단일 시점 체적 결정 다시 평가" }));
    expect(await screen.findByText("DSM이 없어 이 결정을 요청할 수 없습니다.")).toBeTruthy();
    expect(bodies).toHaveLength(0);
  });

  it("explains a BLOCKED single-volume decision with the generated blocker copy", async () => {
    const onSingleVolumeDecisionChange = vi.fn();
    fetchMock.mockImplementation(singleVolumeFetch(["blocked"], [], []));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite onSingleVolumeDecisionChange={onSingleVolumeDecisionChange} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("단일 시점 체적 작업구역").querySelectorAll("option")).toHaveLength(2));
    fireEvent.change(screen.getByLabelText("단일 시점 체적 작업구역"), { target: { value: "pile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "단일 시점 체적 결정 다시 평가" }));
    expect(await screen.findByText("단일 시점 체적 매핑이 없습니다")).toBeTruthy();
    expect(screen.getByText("관리자에게 이 산출물과 구역에 대한 단일 시점 체적 매핑 등록을 요청하세요.")).toBeTruthy();
    expect(onSingleVolumeDecisionChange).toHaveBeenLastCalledWith(expect.objectContaining({ verdict: "BLOCKED" }));
  });
});
