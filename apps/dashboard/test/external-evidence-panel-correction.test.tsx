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

// 서버 page가 주입하는 계정 연속성 비교값과 같은 형태 — 원문 식별자가 아니다.
const fp = () => ({ fingerprint: `v1-${"a".repeat(64)}` });

// 생산 계약 형태의 subject/zone 증인. submissionId는 Core 내부 불투명 식별자로,
// 화면의 제출 참조(ers-v1-…)와 변환·대조하지 않는다(독립 증인 없음).
const contractSubject = (workOrderId: string, revision: number, submissionId: string, siteId = "site-1", organizationId = "org-1") => ({
  organizationId,
  siteId,
  workOrderId,
  submissionId,
  revision,
  submissionDigest: `sha256:${"c".repeat(64)}`,
  manifestDigest: `sha256:${"d".repeat(64)}`,
});
const contractZone = (zoneId: string) => ({
  zoneId,
  revision: 3,
  definitionDigest: `sha256:${"2".repeat(64)}`,
  observedCrsDigest: `sha256:${"3".repeat(64)}`,
  observedVerticalReferenceDigest: `sha256:${"4".repeat(64)}`,
});

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

it("shows the full submission reference only for colliding sealed targets and keeps distinct targets merge-free", async () => {
  const duplicate = {
    submissionRef: ref("b"),
    state: "SEALED" as const,
    submission: {
      revision: 1,
      artifacts: [{ artifactId: "dsm", kind: "dsm", fileName: "current.tif" }],
    },
  };
  const distinct = {
    submissionRef: ref("f"),
    state: "SEALED" as const,
    submission: {
      revision: 1,
      artifacts: [{ artifactId: "dsm", kind: "dsm", fileName: "other.tif" }],
    },
  };
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith("/evidence")) return response({ items: [] });
    if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
    if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, duplicate, distinct]} canWrite={false} />);

  expect(await screen.findByText(`제출 식별자 · ${current.submissionRef}`)).toBeTruthy();
  expect(screen.getByText(`제출 식별자 · ${duplicate.submissionRef}`)).toBeTruthy();
  expect(screen.queryByText(`제출 식별자 · ${distinct.submissionRef}`)).toBeNull();
  expect(screen.getAllByRole("button", { name: /current\.tif/ })).toHaveLength(2);
});

it("marks the selected sealed target and names its scope in the decision area", async () => {
  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite={false} />);
  const target = await screen.findByRole("button", { name: /current\.tif/ });
  expect(target.getAttribute("aria-current")).toBeNull();
  fireEvent.click(target);
  expect(target.getAttribute("aria-current")).toBe("true");
  expect(target.textContent).toContain("선택됨");
  expect(screen.getByRole("heading", { name: /선택한 등록본/ })).toBeTruthy();
});

it("announces decision validation failures as alerts with visible field labels", async () => {
  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  // 보이는 라벨이 그대로 라벨 연결된다.
  expect(screen.getByLabelText("비교할 이전 등록 버전")).toBeTruthy();
  expect(screen.getByLabelText("변화 분석 구역")).toBeTruthy();
  expect(screen.getByLabelText("한 시점 측정 구역")).toBeTruthy();
  expect(screen.getByLabelText("과거 판정 기록 참조")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
  const missing = await screen.findByText("비교할 이전 등록 버전을 선택하세요.");
  expect(missing.getAttribute("role")).toBe("alert");
  fireEvent.change(screen.getByLabelText("과거 판정 기록 참조"), { target: { value: "bogus" } });
  fireEvent.click(screen.getByRole("button", { name: "과거 기록 조회" }));
  const invalid = await screen.findByText("유효한 과거 판정 기록 참조를 입력하세요.");
  expect(invalid.getAttribute("role")).toBe("alert");
});

it("restarts evidence with a new key only after an explicit new start", async () => {
  vi.stubGlobal("crypto", {
    randomUUID: () => "stable-key",
    subtle: { digest: async () => new Uint8Array(32).buffer },
  });
  const declarationKeys: string[] = [];
  let sealCalls = 0;
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/evidence") && !init?.method) return response({ items: [] });
    if (url.endsWith("/evidence") && init?.method === "POST") {
      declarationKeys.push((init.headers as Record<string, string>)["idempotency-key"]);
      const declared = JSON.parse(String(init?.body)) as { independenceBasis: string };
      return response({
        evidenceRef: `eev-v1-${"a".repeat(64)}`,
        state: "DECLARED",
        targetDsmArtifactId: "dsm",
        declaredContentDigest: `sha256:${"0".repeat(64)}`,
        declaredContentType: "text/csv",
        independenceBasis: declared.independenceBasis,
      });
    }
    if (url.endsWith("/upload-grant")) return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, uploadUrl: "https://upload.test/checkpoints", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
    if (url === "https://upload.test/checkpoints") return response({});
    if (url.endsWith("/seal")) {
      sealCalls += 1;
      return { ok: false, json: async () => ({}) };
    }
    if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
    if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
    throw new Error(`unexpected fetch ${url}`);
  });
  const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
  Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
  fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
  fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
  expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
  // 실패 뒤에는 같은 키 재시도가 기본이고, 입력은 잠긴다.
  expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "다른 파일·선언으로 새로 시작" }));
  // 확인 전에는 해제되지 않고 새 키도 나가지 않는다.
  expect(await screen.findByText(/이전 증거 요청이 이미 접수됐을 수 있습니다/)).toBeTruthy();
  expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "새로 시작 확인" }));
  expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(false);
  expect(screen.getByText(/다른 파일·선언으로 새로 시작합니다/)).toBeTruthy();
  // 새 시작 뒤의 제출도 같은 흐름으로 동작한다.
  fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량 2" } });
  fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
  await waitFor(() => expect(declarationKeys).toHaveLength(2));
  await waitFor(() => expect(sealCalls).toBe(2));
});

it("renders only the Core-recorded checkpoint aggregate and labels independence as a declaration", async () => {
  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite={false} />);

  expect(await screen.findByText("분석 시스템 측정 집계")).toBeTruthy();
  expect(screen.getByText("검사점 3개 · 평균 오차 -0.02m · MAE 0.04m · RMSE 0.05m")).toBeTruthy();
  expect(screen.getByText("분석 시스템 기록 시각: 2026. 9. 9. 09:00")).toBeTruthy();
  expect(screen.getByText("제출자가 적은 독립 근거: 현장 재구성과 독립된 측량")).toBeTruthy();
  expect(screen.getByText("이 내용은 제출자가 적은 것으로, 분석 시스템이 독립성을 증명한 것은 아닙니다.")).toBeTruthy();
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

  expect(await screen.findByText("분석 시스템 집계 대기")).toBeTruthy();
  expect(screen.getByText("DSM 없음: 표시는 가능하지만 독립 검사점·높이 확인·변화 분석은 제한됩니다.")).toBeTruthy();
  expect((await screen.findByRole("alert")).textContent).toContain("독립 검사점 증거를 읽지 못했습니다.");
});

it("keeps evidence readable but blocks new evidence and use decisions after closure", async () => {
  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite newIntentAllowed={false} />);

  expect(await screen.findByText(/업무 종료 상태입니다. 새 증거와 사용 결정은 요청할 수 없지만/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /current\.tif/ }));
  expect((screen.getByRole("button", { name: "화면 표시 다시 확인" }) as HTMLButtonElement).disabled).toBe(true);
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
      return response({ decision: { decisionId: `external-use-decision-${use[0].repeat(32)}`, decisionDigest: `sha256:${use[0].repeat(64)}`, subject: contractSubject("current", 1, "sub-current-1"), subjectDigest: `sha256:${"e".repeat(64)}`, use, verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
    }
    if (url.endsWith("/pair")) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      pairBodies.push(body);
      return response({ decision: { decisionId: `external-use-decision-${String(body.use)[0].repeat(32)}`, decisionDigest: `sha256:${String(body.use)[0].repeat(64)}`, baselineSubject: contractSubject(String(body.baselineWorkOrderId), Number(body.baselineRevision), "sub-baseline-2"), baselineSubjectDigest: `sha256:${"e".repeat(64)}`, currentSubject: contractSubject("current", 1, "sub-current-1"), currentSubjectDigest: `sha256:${"f".repeat(64)}`, use: body.use, ...(body.use === "RELATIVE_VOLUME" ? { zone: contractZone("area-1") } : {}), verdict: "RESTRICTED", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} onRelativeVolumeDecisionChange={onRelativeVolumeDecisionChange} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
  const options = [...screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")];
  expect(options.map((option) => option.textContent).join(" ")).not.toContain("ers-v1-");
  expect(options.map((option) => option.textContent).join(" ")).toContain("same-work-order.tif");
  expect(options.map((option) => option.textContent).join(" ")).toContain("other-work-order.tif");

  fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), {
    target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` },
  });
  fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
  fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
  expect(await screen.findByText(/현재 분석 시스템 판정: 화면 표시/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "높이 다시 확인" }));
  expect(await screen.findByText(/현재 분석 시스템 판정: 높이 확인/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
  expect(await screen.findByText(/현재 분석 시스템 판정: 눈으로 비교/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
  expect(await screen.findByText(/현재 분석 시스템 판정: 변화 분석\(두 시점 비교\)/)).toBeTruthy();

  expect(screen.getByText(/현재 분석 시스템 판정: 화면 표시/)).toBeTruthy();
  expect(screen.getByText(/현재 분석 시스템 판정: 높이 확인/)).toBeTruthy();
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
        return Promise.resolve(response({ decision: { decisionId: `external-use-decision-${"d".repeat(32)}`, decisionDigest: `sha256:${"d".repeat(64)}`, subject: contractSubject("current", 1, "sub-current-1"), subjectDigest: `sha256:${"e".repeat(64)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } }));
      }
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, next]} canWrite accountIdentity={fp()} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
  expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
  const firstHeader = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/single"))?.[1] as RequestInit;
  fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
  await waitFor(() => expect(oldSignal).toBeDefined());
  const secondHeader = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/single"))[1]?.[1] as RequestInit;
  expect((firstHeader.headers as Record<string, string>)["idempotency-key"]).toBe((secondHeader.headers as Record<string, string>)["idempotency-key"]);

  fireEvent.click(screen.getByRole("button", { name: /next\.tif/ }));
  expect(oldSignal?.aborted).toBe(true);
  resolveLate?.(response({ decision: { decisionId: `external-use-decision-${"f".repeat(32)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } }));
  await waitFor(() => expect(screen.queryByText(/현재 분석 시스템 판정: 화면 표시/)).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
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

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
  fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
  fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
  expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));

  expect(await screen.findByText("분석 시스템이 같은 파일을 이미 받았습니다.")).toBeTruthy();
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
  fireEvent.change(screen.getByLabelText("과거 판정 기록 참조"), { target: { value: historicalId } });
  fireEvent.click(screen.getByRole("button", { name: "과거 기록 조회" }));

  expect(await screen.findByText(/과거 판정 기록: 화면 표시/)).toBeTruthy();
  expect(screen.getByText(`판정 식별자: ${historicalId}`)).toBeTruthy();
  expect(screen.getByText(`판정 확인값(해시): ${historicalDecision.decisionDigest}`)).toBeTruthy();
  expect(screen.getByText("원본 보관용 식별자 · 조직 org-1 · 현장 site-1 · 작업 current")).toBeTruthy();
  expect(screen.getByText(`제출 식별자 ${current.submissionRef} · 제출 확인값(해시) ${historicalDecision.subject.submissionDigest}`)).toBeTruthy();
  expect(screen.getByText(`목록 확인값(해시) ${historicalDecision.subject.manifestDigest} · 대상 확인값(해시) ${historicalDecision.subjectDigest}`)).toBeTruthy();
  expect(screen.getByText(`정책 확인값(해시): ${historicalDecision.policyDigest}`)).toBeTruthy();
  expect(screen.getByText(`검사 보고서 확인값(해시): ${historicalDecision.inspectionReportDigest}`)).toBeTruthy();
  expect(screen.getByText(`증거 기록 확인값(해시): ${historicalDecision.evidenceRecordDigests.join(", ")}`)).toBeTruthy();
  expect(screen.getByText(`표시 영수증 확인값(해시): ${historicalDecision.sanitizedDisplayReceiptDigest}`)).toBeTruthy();
  expect(screen.getByText("과거 기록은 현재 사용 권한이나 실행 권한이 아닙니다.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "화면 표시 다시 확인" })).toBeNull();
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
  fireEvent.change(screen.getByLabelText("과거 판정 기록 참조"), { target: { value: historicalId } });
  fireEvent.click(screen.getByRole("button", { name: "과거 기록 조회" }));

  expect(await screen.findByText(/과거 판정 기록: 변화 분석\(두 시점 비교\)/)).toBeTruthy();
  expect(screen.getByText(`판정 식별자: ${historicalId}`)).toBeTruthy();
  expect(screen.getByText(`판정 확인값(해시): ${pairDecision.decisionDigest}`)).toBeTruthy();
  expect(screen.getByText("계약 버전: external-pair-use-decision-v1")).toBeTruthy();
  expect(screen.getByText("원본 보관용 식별자 · 조직 org-1 · 현장 site-1 · 작업 baseline-work-order")).toBeTruthy();
  expect(screen.getByText(`제출 식별자 ${sameWorkOrderBaseline.submissionRef} · 제출 확인값(해시) ${baseline.submissionDigest}`)).toBeTruthy();
  expect(screen.getByText(`목록 확인값(해시) ${baseline.manifestDigest} · 대상 확인값(해시) ${pairDecision.baselineSubjectDigest}`)).toBeTruthy();
  expect(screen.getByText("원본 보관용 식별자 · 조직 org-1 · 현장 site-1 · 작업 current")).toBeTruthy();
  expect(screen.getByText(`제출 식별자 ${current.submissionRef} · 제출 확인값(해시) ${currentSubject.submissionDigest}`)).toBeTruthy();
  expect(screen.getByText(`목록 확인값(해시) ${currentSubject.manifestDigest} · 대상 확인값(해시) ${pairDecision.currentSubjectDigest}`)).toBeTruthy();
  expect(screen.getByText(`정책 확인값(해시): ${pairDecision.policyDigest}`)).toBeTruthy();
  expect(screen.getByText(`기준 검사 보고서 확인값(해시): ${pairDecision.baselineInspectionReportDigest}`)).toBeTruthy();
  expect(screen.getByText(`현재 검사 보고서 확인값(해시): ${pairDecision.currentInspectionReportDigest}`)).toBeTruthy();
  expect(screen.getByText(`증거 기록 확인값(해시): ${pairDecision.evidenceRecordDigests.join(", ")}`)).toBeTruthy();
  expect(screen.getByText(`기준 표시 영수증 확인값(해시): ${pairDecision.baselineSanitizedDisplayReceiptDigest}`)).toBeTruthy();
  expect(screen.getByText(`현재 표시 영수증 확인값(해시): ${pairDecision.currentSanitizedDisplayReceiptDigest}`)).toBeTruthy();
  expect(screen.getByText("비교 구역: area-1 · 구역 버전 3")).toBeTruthy();
  expect(screen.getByText(`작업구역 정의 확인값(해시): ${pairDecision.zone.definitionDigest}`)).toBeTruthy();
  expect(screen.getByText(`관측 좌표계 확인값(해시): ${pairDecision.zone.observedCrsDigest}`)).toBeTruthy();
  expect(screen.getByText(`관측 수직 기준 확인값(해시): ${pairDecision.zone.observedVerticalReferenceDigest}`)).toBeTruthy();
  expect(screen.getByText(`호환성 매핑 확인값(해시): ${pairDecision.compatibilityMappingDigest}`)).toBeTruthy();
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

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  expect((await screen.findByRole("alert")).textContent).toContain("일부 같은 현장 작업의 비교 대상을 읽지 못했습니다: 누락 기준. 목록이 완전하지 않습니다.");
  expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(2);

  recovered = true;
  fireEvent.click(screen.getByRole("button", { name: "비교 대상 다시 시도" }));
  await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("holds a pending pair request across baseline and zone changes so no second scoped request runs", async () => {
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
      signals.push(init?.signal as AbortSignal);
      return new Promise(() => undefined);
    }
    throw new Error(`unexpected fetch ${url}`);
  });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
  fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
  fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-a" } });
  fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
  await waitFor(() => expect(pairAttempts).toBe(1));

  // 진행 중인 확인을 중단하거나 같은 확인을 두 번 보내지 않는다. 중단해도 Core
  // 기록은 되돌릴 수 없고, 다른 키로 다시 보내면 중복 기록이 생긴다.
  fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${secondBaseline.submissionRef}:1` } });
  expect(signals[0].aborted).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
  await waitFor(() => expect(pairAttempts).toBe(1));
  expect(signals).toHaveLength(1);

  fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
  await waitFor(() => expect(pairAttempts).toBe(1));
  fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-b" } });
  expect(signals[0].aborted).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
  await waitFor(() => expect(pairAttempts).toBe(1));
  expect(signals).toHaveLength(1);
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
      return Promise.resolve(response({ decision: { decisionId: `external-use-decision-${"f".repeat(32)}`, decisionDigest: `sha256:${"f".repeat(64)}`, subject: contractSubject("current", 1, "sub-current-1"), subjectDigest: `sha256:${"e".repeat(64)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } }));
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
  Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });

  render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, next]} canWrite accountIdentity={fp()} />);
  fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
  fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
  fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
  await waitFor(() => expect(evidenceSignal).toBeDefined());

  fireEvent.click(screen.getByRole("button", { name: /next\.tif/ }));
  expect(evidenceSignal?.aborted).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
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
            subject: contractSubject("current", 1, "sub-current-1"),
            subjectDigest: `sha256:${"e".repeat(64)}`,
            use: "SINGLE_VOLUME",
            verdict: outcome === "blocked" ? "BLOCKED" : "ELIGIBLE",
            reasons: outcome === "blocked" ? ["SINGLE_VOLUME_MAPPING_UNAVAILABLE"] : [],
            remediations: outcome === "blocked" ? ["AUTHORIZE_SINGLE_VOLUME_MAPPING"] : [],
            decidedAt: "2026-09-17T00:00:00Z",
            ...(outcome === "blocked" ? {} : { zone: contractZone("pile-1") }),
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

    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} onSingleVolumeDecisionChange={onSingleVolumeDecisionChange} onRelativeVolumeDecisionChange={onRelativeVolumeDecisionChange} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("한 시점 측정 구역").querySelectorAll("option")).toHaveLength(2));

    fireEvent.click(screen.getByRole("button", { name: "한 시점 측정 다시 확인" }));
    expect(await screen.findByText("한 시점 측정 구역을 선택하세요.")).toBeTruthy();
    expect(bodies).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("한 시점 측정 구역"), { target: { value: "pile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "한 시점 측정 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "한 시점 측정 다시 확인" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 한 시점 측정/)).toBeTruthy();

    expect(bodies).toEqual([{ zoneId: "pile-1" }, { zoneId: "pile-1" }]);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/pair"))).toBe(false);
    expect((screen.getByLabelText("비교할 이전 등록 버전") as HTMLSelectElement).value).toBe("");
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
    await waitFor(() => expect(screen.getByLabelText("한 시점 측정 구역").querySelectorAll("option")).toHaveLength(2));
    fireEvent.change(screen.getByLabelText("한 시점 측정 구역"), { target: { value: "pile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "한 시점 측정 다시 확인" }));
    expect(await screen.findByText("DSM이 없어 이 확인을 요청할 수 없습니다.")).toBeTruthy();
    expect(bodies).toHaveLength(0);
  });

  it("explains a BLOCKED single-volume decision with the generated blocker copy", async () => {
    const onSingleVolumeDecisionChange = vi.fn();
    fetchMock.mockImplementation(singleVolumeFetch(["blocked"], [], []));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} onSingleVolumeDecisionChange={onSingleVolumeDecisionChange} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("한 시점 측정 구역").querySelectorAll("option")).toHaveLength(2));
    fireEvent.change(screen.getByLabelText("한 시점 측정 구역"), { target: { value: "pile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "한 시점 측정 다시 확인" }));
    expect(await screen.findByText("단일 시점 체적 매핑이 없습니다")).toBeTruthy();
    expect(screen.getByText("관리자에게 이 산출물과 구역에 대한 단일 시점 체적 매핑 등록을 요청하세요.")).toBeTruthy();
    expect(onSingleVolumeDecisionChange).toHaveBeenLastCalledWith(expect.objectContaining({ verdict: "BLOCKED" }));
  });
});

describe("use-decision account-continuity client guard", () => {
  const continuityFetch = (outcomes: Array<{ status: number; code?: string }>, calls: Array<{ key: string; body: unknown; continuity: string | null }>) =>
    async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence")) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/use-decisions/single")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        calls.push({ key: headers["idempotency-key"], body: JSON.parse(String(init?.body)), continuity: headers["x-ksi-continuity-fingerprint"] ?? null });
        const outcome = outcomes[calls.length - 1] ?? { status: 201 };
        if (outcome.status === 201) {
          return response({ decision: { decisionId: `external-use-decision-${"d".repeat(32)}`, decisionDigest: `sha256:${"d".repeat(64)}`, subject: contractSubject("current", 1, "sub-current-1"), subjectDigest: `sha256:${"e".repeat(64)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
        }
        return { ok: false, status: outcome.status, json: async () => (outcome.code ? { code: outcome.code } : {}) };
      }
      throw new Error(`unexpected fetch ${url}`);
    };

  it("reuses the frozen key, body and continuity for a retry even after the draft changes", async () => {
    const calls: Array<{ key: string; body: unknown; continuity: string | null }> = [];
    fetchMock.mockImplementation(continuityFetch([{ status: 0 }, { status: 201 }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(calls).toHaveLength(1);
    expect(calls[0].continuity).toBe(fp().fingerprint);

    // 재시도 전에 화면 선택을 건드려도 동결된 원래 요청으로 나간다.
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 화면 표시/)).toBeTruthy();
    expect(calls).toHaveLength(2);
    expect(calls[1].key).toBe(calls[0].key);
    expect(calls[1].body).toEqual(calls[0].body);
    expect(calls[1].continuity).toBe(fp().fingerprint);
  });

  it("blocks a new attempt without a bound identity but keeps the frozen retry", async () => {
    const calls: Array<{ key: string; body: unknown; continuity: string | null }> = [];
    fetchMock.mockImplementation(continuityFetch([{ status: 201 }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    expect(screen.getAllByText(/계정을 확인하지 못해 새 확인 요청을 시작할 수 없습니다/).length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(screen.getAllByText(/계정을 확인하지 못해 새 확인 요청을 시작할 수 없습니다/).length).toBeGreaterThanOrEqual(1);
    expect(calls).toHaveLength(0);
  });

  it("keeps the frozen request on an account-continuity block and does not claim a rejection", async () => {
    const calls: Array<{ key: string; body: unknown; continuity: string | null }> = [];
    fetchMock.mockImplementation(continuityFetch([{ status: 0 }, { status: 409, code: "ACCOUNT_CONTINUITY_MISMATCH" }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    const frozenKey = calls[0].key;
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/계정이 바뀌어 같은 확인 요청을 다시 보내지 않았습니다/)).toBeTruthy();
    expect(await screen.findByText(/이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();
    expect(calls).toHaveLength(2);
    expect(calls[1].key).toBe(frozenKey);
  });

  it("treats a first-attempt refusal as definitive and a retry refusal as uncertain", async () => {
    const calls: Array<{ key: string; body: unknown; continuity: string | null }> = [];
    fetchMock.mockImplementation(continuityFetch([
      { status: 403 },
      { status: 0 },
      { status: 403 },
    ], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    // 첫 시도 403 — 권한 검사 다음에 결정이 없으므로 기록되지 않았다고 단정한다.
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/이 확인을 요청할 권한이 없습니다. 판정은 기록되지 않았습니다/)).toBeTruthy();
    // 모호한 첫 시도 뒤의 재시도 403 — 이전 요청이 처리됐을 수 있으므로 단정하지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/다시 보낸 요청이 권한 부족으로 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();
    expect(new Set(calls.map((call) => call.key)).size).toBe(1);
  });

  it("warns before an explicit new intent after a recorded decision", async () => {
    const calls: Array<{ key: string; body: unknown; continuity: string | null }> = [];
    fetchMock.mockImplementation(continuityFetch([{ status: 201 }, { status: 201 }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 화면 표시/)).toBeTruthy();
    expect(calls).toHaveLength(1);

    // 기록 뒤의 같은 버튼은 명시적 새 의도 — 경고 없이 새 키를 만들지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(screen.getAllByText(/새로 요청하면 같은 조건이라도 다른 판정 기록이 생길 수 있습니다/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: "새 확인 요청 계속" })).toBeTruthy();
    expect(calls).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "새 확인 요청 계속" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 화면 표시/)).toBeTruthy();
    expect(calls).toHaveLength(2);
    expect(calls[1].key).not.toBe(calls[0].key);
  });

  it("re-warns when the draft moves between the fresh warning and its confirmation", async () => {
    const calls: Array<{ body: Record<string, unknown>; key: string }> = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence")) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") {
        return response({ workOrders: [{ workOrderId: "current", name: "현재 작업" }, { workOrderId: "other", name: "다른 작업" }] });
      }
      if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") {
        return response({ submissions: [current, sameWorkOrderBaseline] });
      }
      if (url === "/api/observation-work-orders/other/external-reconstruction-submissions") {
        return response({ submissions: [otherWorkOrderBaseline] });
      }
      if (url.endsWith("/pair")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        const pairBody = JSON.parse(String(init?.body)) as { use: string; baselineWorkOrderId: string; baselineRevision: number };
        calls.push({ body: pairBody, key: headers["idempotency-key"] });
        return response({ decision: { decisionId: `external-use-decision-${"e".repeat(32)}`, decisionDigest: `sha256:${"e".repeat(64)}`, baselineSubject: contractSubject(pairBody.baselineWorkOrderId, pairBody.baselineRevision, "sub-baseline-2"), baselineSubjectDigest: `sha256:${"e".repeat(64)}`, currentSubject: contractSubject("current", 1, "sub-current-1"), currentSubjectDigest: `sha256:${"f".repeat(64)}`, use: "VISUAL_COMPARISON", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 눈으로 비교/)).toBeTruthy();
    expect(calls).toHaveLength(1);

    // 경고 뒤에 비교 대상을 바꾸면 확인이 닫히고, 다음 누름은 바뀐 조건에 대해
    // 다시 경고한다. 바뀐 조건을 경고 없이 보내지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
    expect(screen.getByRole("button", { name: "새 확인 요청 계속" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `other:${otherWorkOrderBaseline.submissionRef}:1` } });
    expect(screen.queryByRole("button", { name: "새 확인 요청 계속" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
    expect(await screen.findByText(/이미 확인된 판정 기록이 있습니다/)).toBeTruthy();
    expect(calls).toHaveLength(1);

    // 바뀐 조건의 경고를 다시 확인해야만 보낸다.
    fireEvent.click(screen.getByRole("button", { name: "새 확인 요청 계속" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 눈으로 비교/)).toBeTruthy();
    expect(calls).toHaveLength(2);
    expect(calls[1].key).not.toBe(calls[0].key);
    expect(calls[1].body).toMatchObject({ baselineWorkOrderId: "other" });
  });

  it("hides guaranteed-403 legacy decision actions for scoped release accounts without hiding evidence", async () => {
    const calls: unknown[] = [];
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/evidence")) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/use-decisions/single")) {
        calls.push(url);
        return response({ decision: { decisionId: `external-use-decision-${"d".repeat(32)}` } });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    render(
      <ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} legacyDecisionClosed />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));

    // 확정 403이 되는 요청 버튼·기록 조회는 내놓지 않는다.
    expect(screen.queryByRole("button", { name: "화면 표시 다시 확인" })).toBeNull();
    expect(screen.queryByRole("button", { name: "높이 다시 확인" })).toBeNull();
    expect(screen.queryByRole("button", { name: "눈으로 비교 다시 확인" })).toBeNull();
    expect(screen.queryByRole("button", { name: "변화 분석 다시 확인" })).toBeNull();
    expect(screen.queryByRole("button", { name: "한 시점 측정 다시 확인" })).toBeNull();
    expect(screen.queryByText("과거 판정 기록 조회")).toBeNull();
    expect(calls).toHaveLength(0);

    // 닫힘 안내와 지원 경로 연결은 보이고, 허용된 증거·검사 기록은 그대로 둔다.
    // 기존 판정 기록의 존재 여부는 단정하지 않는다.
    expect(screen.getByText("사용 결정 요청 닫힘")).toBeTruthy();
    expect(screen.getByText(/현재 계정의 배포 범위에 열려 있지 않아 보낼 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/이 화면에서는 새로운 사용 결정 요청을 보내지 않습니다/)).toBeTruthy();
    expect(screen.queryByText(/판정이 기록되지 않았습니다/)).toBeNull();
    expect(screen.getByText(/새로운 두 시점 관측 변화 분석은 현장의 분석 화면에서 진행합니다/)).toBeTruthy();
    expect(screen.queryByText(/정량 비교·측정/)).toBeNull();
    const handoff = screen.getByRole("link", { name: "분석 화면 열기" });
    expect(handoff.getAttribute("href")).toBe("/sites/site-1/analysis");
    expect(screen.getByLabelText("독립 검사점 CSV")).toBeTruthy();
    expect(screen.getByLabelText("독립성 근거 선언")).toBeTruthy();
  });

  it("keeps legacy decision actions for ambiguous (non-scoped) identities", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/evidence")) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      throw new Error(`unexpected fetch ${url}`);
    });
    render(
      <ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} legacyDecisionClosed={false} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    expect(screen.getByRole("button", { name: "화면 표시 다시 확인" })).toBeTruthy();
    expect(screen.getByText("과거 판정 기록 조회")).toBeTruthy();
    expect(screen.queryByText("사용 결정 요청 닫힘")).toBeNull();
  });
});

describe("use-decision retry refusal honesty", () => {
  const trackFetch = (script: Array<{ status: number; code?: string }>, calls: Array<{ key: string; body: unknown; continuity: string | null }>) =>
    async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence")) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") {
        return response({ workAreas: [{ workAreaId: "pile-1", name: "야적장 1", status: "ACTIVE" }] });
      }
      if (url === "/api/sites/site-1/observation-work-orders") {
        return response({ workOrders: [{ workOrderId: "current", name: "현재 작업" }, { workOrderId: "other", name: "다른 작업" }] });
      }
      if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") {
        return response({ submissions: [current, sameWorkOrderBaseline] });
      }
      if (url === "/api/observation-work-orders/other/external-reconstruction-submissions") {
        return response({ submissions: [otherWorkOrderBaseline] });
      }
      if (url.includes("/use-decisions/")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        calls.push({ key: headers["idempotency-key"], body: JSON.parse(String(init?.body)), continuity: headers["x-ksi-continuity-fingerprint"] ?? null });
        const step = script[calls.length - 1] ?? { status: 201 };
        if (step.status === 201) {
          return response({ decision: { decisionId: `external-use-decision-${"d".repeat(32)}`, decisionDigest: `sha256:${"d".repeat(64)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
        }
        if (step.status === 0) return { ok: false, status: 0, json: async () => ({}) };
        return { ok: false, status: step.status, json: async () => (step.code ? { code: step.code } : {}) };
      }
      throw new Error(`unexpected fetch ${url}`);
    };

  it.each([
    { code: "INVALID_EXTERNAL_USE_INTENT", button: "화면 표시 다시 확인" },
    { code: "INVALID_EXTERNAL_PAIR_INTENT", button: "눈으로 비교 다시 확인" },
    { code: "INVALID_EXTERNAL_SINGLE_VOLUME_INTENT", button: "한 시점 측정 다시 확인" },
  ])("does not claim no record on a retry $code refusal", async ({ code, button }) => {
    const calls: Array<{ key: string; body: unknown; continuity: string | null }> = [];
    fetchMock.mockImplementation(trackFetch([{ status: 0 }, { status: 400, code }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    if (button === "눈으로 비교 다시 확인") {
      await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
      fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    }
    if (button === "한 시점 측정 다시 확인") {
      await waitFor(() => expect(screen.getByLabelText("한 시점 측정 구역").querySelectorAll("option")).toHaveLength(2));
      fireEvent.change(screen.getByLabelText("한 시점 측정 구역"), { target: { value: "pile-1" } });
    }
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: button }));
    // 재시도 거부는 이전 요청의 성패를 증명하지 않는다 — 미확인으로 둔다.
    expect(await screen.findByText(/이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();
    expect(screen.queryByText(/판정은 기록되지 않았습니다/)).toBeNull();
    expect(calls).toHaveLength(2);
    expect(calls[1].key).toBe(calls[0].key);
    expect(calls[1].continuity).toBe(fp().fingerprint);
  });

  it.each([
    { code: "INVALID_EXTERNAL_USE_INTENT", button: "화면 표시 다시 확인" },
    { code: "INVALID_EXTERNAL_PAIR_INTENT", button: "눈으로 비교 다시 확인" },
    { code: "INVALID_EXTERNAL_SINGLE_VOLUME_INTENT", button: "한 시점 측정 다시 확인" },
  ])("keeps the original attempt when a first $code response has ambiguous origin", async ({ code, button }) => {
    const calls: Array<{ key: string; body: unknown; continuity: string | null }> = [];
    fetchMock.mockImplementation(trackFetch([{ status: 400, code }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    if (button === "눈으로 비교 다시 확인") {
      await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
      fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    }
    if (button === "한 시점 측정 다시 확인") {
      await waitFor(() => expect(screen.getByLabelText("한 시점 측정 구역").querySelectorAll("option")).toHaveLength(2));
      fireEvent.change(screen.getByLabelText("한 시점 측정 구역"), { target: { value: "pile-1" } });
    }
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(await screen.findByText(/기록되었는지 확인할 수 없으니/)).toBeTruthy();
    expect(screen.queryByText(/판정은 기록되지 않았습니다/)).toBeNull();
    expect(calls).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: button }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toEqual(calls[0]);
  });
});

describe("changed-selection new-intent guard", () => {
  const guardFetch = (script: Array<{ status: number }>, calls: Array<{ key: string; body: Record<string, unknown>; continuity: string | null }>) =>
    async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence")) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") {
        return response({ workOrders: [{ workOrderId: "current", name: "현재 작업" }, { workOrderId: "other", name: "다른 작업" }] });
      }
      if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") {
        return response({ submissions: [current, sameWorkOrderBaseline] });
      }
      if (url === "/api/observation-work-orders/other/external-reconstruction-submissions") {
        return response({ submissions: [otherWorkOrderBaseline] });
      }
      if (url.endsWith("/single") || url.endsWith("/pair")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        calls.push({ key: headers["idempotency-key"], body, continuity: headers["x-ksi-continuity-fingerprint"] ?? null });
        const step = script[calls.length - 1] ?? { status: 201 };
        if (step.status === 201) {
          const requestBody = body as { use?: unknown; baselineWorkOrderId?: unknown; baselineRevision?: unknown; zoneId?: unknown };
          const endpointUse = url.endsWith("/single-volume") ? "SINGLE_VOLUME" : requestBody.use;
          const contractDecision: Record<string, unknown> = {
            decisionId: `external-use-decision-${"e".repeat(32)}`,
            decisionDigest: `sha256:${"e".repeat(64)}`,
            use: endpointUse,
            verdict: "ELIGIBLE",
            reasons: [],
            remediations: [],
            decidedAt: "2026-09-09T00:00:00Z",
          };
          if (url.endsWith("/pair")) {
            contractDecision.baselineSubject = contractSubject(String(requestBody.baselineWorkOrderId), Number(requestBody.baselineRevision), "sub-baseline-x");
            contractDecision.baselineSubjectDigest = `sha256:${"e".repeat(64)}`;
            contractDecision.currentSubject = contractSubject("current", 1, "sub-current-1");
            contractDecision.currentSubjectDigest = `sha256:${"f".repeat(64)}`;
            if (requestBody.use === "RELATIVE_VOLUME") contractDecision.zone = contractZone(String(requestBody.zoneId ?? "area-1"));
          } else {
            contractDecision.subject = contractSubject("current", 1, "sub-current-1");
            contractDecision.subjectDigest = `sha256:${"e".repeat(64)}`;
            if (url.endsWith("/single-volume")) contractDecision.zone = contractZone(String(requestBody.zoneId ?? "pile-1"));
          }
          return response({ decision: contractDecision });
        }
        return { ok: false, status: step.status, json: async () => ({}) };
      }
      throw new Error(`unexpected fetch ${url}`);
    };

  it.each([
    { button: "화면 표시 다시 확인", receipt: /현재 분석 시스템 판정: 화면 표시/ },
    { button: "높이 다시 확인", receipt: /현재 분석 시스템 판정: 높이 확인/ },
  ])("reuses the original key and body for $button when only an unrelated selection changes", async ({ button, receipt }) => {
    const calls: Array<{ key: string; body: Record<string, unknown>; continuity: string | null }> = [];
    fetchMock.mockImplementation(guardFetch([{ status: 0 }, { status: 201 }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(calls).toHaveLength(1);

    // 단일 확인의 기준 선택은 전송 내용과 무관하므로, 바꿔도 같은 요청이다.
    // 새 의도 확인 없이 동결된 원래 키·내용으로 재시도한다.
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `other:${otherWorkOrderBaseline.submissionRef}:1` } });
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(await screen.findByText(receipt)).toBeTruthy();
    expect(calls).toHaveLength(2);
    expect(calls[1].key).toBe(calls[0].key);
    expect(calls[1].body).toEqual(calls[0].body);
    expect(calls[1].continuity).toBe(fp().fingerprint);
    expect(screen.queryByRole("button", { name: "새 확인 요청 계속" })).toBeNull();
    expect(screen.queryByText(/이미 확인된 판정 기록이 있습니다/)).toBeNull();
    expect(screen.queryByText(/이전에 확인 요청을 보냈습니다/)).toBeNull();
  });

  it("retries the same frozen request after a definitive first refusal and an unrelated change", async () => {
    const calls: Array<{ key: string; body: Record<string, unknown>; continuity: string | null }> = [];
    fetchMock.mockImplementation(guardFetch([{ status: 403 }, { status: 403 }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    // 첫 시도 확정 거부 — 이 시도에서는 판정이 기록되지 않았다.
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/이 확인을 요청할 권한이 없습니다. 판정은 기록되지 않았습니다/)).toBeTruthy();
    expect(calls).toHaveLength(1);

    // 무관한 기준을 바꿔도 같은 요청이라 경고 없이 같은 키로 재시도한다.
    // 같은 거부가 다시 오고, 새 기록은 생기지 않는다.
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `other:${otherWorkOrderBaseline.submissionRef}:1` } });
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/다시 보낸 요청이 권한 부족으로 접수되지 않았습니다/)).toBeTruthy();
    expect(calls).toHaveLength(2);
    expect(calls[1].key).toBe(calls[0].key);
    expect(calls[1].body).toEqual(calls[0].body);
    expect(screen.queryByRole("button", { name: "새 확인 요청 계속" })).toBeNull();
    expect(screen.queryByText(/이미 확인된 판정 기록이 있습니다/)).toBeNull();
    expect(screen.queryByText(/이전에 확인 요청을 보냈습니다/)).toBeNull();
  });

  it("still warns a genuine pair change without an identity and blocks the confirmed send", async () => {
    const calls: Array<{ key: string; body: Record<string, unknown>; continuity: string | null }> = [];
    fetchMock.mockImplementation(guardFetch([{ status: 0 }, { status: 201 }], calls));
    const view = render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(calls).toHaveLength(1);

    // 신원을 잃은 화면에서도 바뀐 비교 조건의 새 키는 경고 없이 나가지 않는다.
    // 모호한 이전 시도라 기록 존재를 단정하지 않는다.
    view.rerender(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={null} />);
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `other:${otherWorkOrderBaseline.submissionRef}:1` } });
    fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
    expect(await screen.findByText(/이전에 확인 요청을 보냈습니다/)).toBeTruthy();
    expect(await screen.findByText(/결과를 확인하지 못했다면 판정이 이미 기록됐을 수 있습니다/)).toBeTruthy();
    expect(screen.queryByText(/이미 확인된 판정 기록이 있습니다/)).toBeNull();
    expect(calls).toHaveLength(1);

    // 확인해도 신원 없이는 보내지 않고 동결을 유지한다.
    fireEvent.click(screen.getByRole("button", { name: "새 확인 요청 계속" }));
    expect(screen.getAllByText(/계정을 확인하지 못해 새 확인 요청을 시작할 수 없습니다/).length).toBeGreaterThanOrEqual(2);
    expect(calls).toHaveLength(1);
  });


  it("shows another pair condition's recorded decision as historical and restores the exact receipt on return", async () => {
    const calls: Array<{ key: string; body: Record<string, unknown>; continuity: string | null }> = [];
    fetchMock.mockImplementation(guardFetch([{ status: 201 }], calls));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 눈으로 비교/)).toBeTruthy();
    expect(calls).toHaveLength(1);

    // 다른 비교 조건으로 옮기면 그 판정을 현재 선택의 기록처럼 보이지 않는다.
    // 보존된 기록은 과거 기록으로 둔다. 새 요청은 보내지 않는다.
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `other:${otherWorkOrderBaseline.submissionRef}:1` } });
    expect(await screen.findByText(/과거 판정 기록: 눈으로 비교/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정: 눈으로 비교/)).toBeNull();
    expect(calls).toHaveLength(1);

    // 원래 조건으로 돌아가면 정확한 기록이 그대로 보인다.
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    expect(await screen.findByText(/현재 분석 시스템 판정: 눈으로 비교/)).toBeTruthy();
    expect(screen.queryByText(/과거 판정 기록: 눈으로 비교/)).toBeNull();
    expect(calls).toHaveLength(1);
  });

});

describe("scoped decision closure and issuance synchronizer", () => {
  it("shows the scoped closure explanation and analysis handoff outside the desktop write boundary", async () => {
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite legacyDecisionClosed />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    const heading = await screen.findByText("사용 결정 요청 닫힘");
    const block = heading.closest("div");
    expect(block).not.toBeNull();
    // Always visible: never inside the lg-only boundary.
    expect(block!.closest("div.hidden")).toBeNull();
    expect(block!.querySelector('a[href="/sites/site-1/analysis"]')).not.toBeNull();
    // The mobile desktop-notice must not promise closed decision actions.
    const asides = document.querySelectorAll('[data-responsive-action-notice="EXTERNAL_RECONSTRUCTION_MUTATION"]');
    expect(asides.length).toBeGreaterThan(0);
    asides.forEach((aside) => {
      expect(aside.textContent).not.toContain("사용 결정 요청");
    });
  });

  it("keeps the open-account desktop notice promising evidence and decision work", async () => {
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    const aside = document.querySelector('[data-responsive-action-notice="EXTERNAL_RECONSTRUCTION_MUTATION"]');
    expect(aside).not.toBeNull();
    expect(aside!.textContent).toContain("사용 결정 요청");
    expect(screen.queryByText("사용 결정 요청 닫힘")).toBeNull();
  });

  it("notifies a changed digest or lost verdict for the same decision id instead of keeping the stale decision", async () => {
    const decisionId = `external-use-decision-${"c".repeat(32)}`;
    let pairCalls = 0;
    const onRelativeVolumeDecisionChange = vi.fn();
    fetchMock.mockImplementation(async (url: string) => {
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
        return response({ decision: { decisionId: `external-use-decision-${"d".repeat(32)}`, decisionDigest: `sha256:${"d".repeat(64)}`, subject: contractSubject("current", 1, "sub-current-1"), subjectDigest: `sha256:${"e".repeat(64)}`, use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
      }
      if (url.endsWith("/pair")) {
        pairCalls += 1;
        const digestValue = pairCalls === 1 ? `sha256:${"a".repeat(64)}` : `sha256:${"b".repeat(64)}`;
        const verdict = pairCalls <= 2 ? "ELIGIBLE" : "WITHDRAWN";
        return response({ decision: { decisionId, decisionDigest: digestValue, baselineSubject: contractSubject("current", 2, "sub-baseline-2"), baselineSubjectDigest: `sha256:${"e".repeat(64)}`, currentSubject: contractSubject("current", 1, "sub-current-1"), currentSubjectDigest: `sha256:${"f".repeat(64)}`, use: "RELATIVE_VOLUME", ...(verdict === "ELIGIBLE" ? { zone: contractZone("area-1") } : {}), verdict, reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z" } });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} onRelativeVolumeDecisionChange={onRelativeVolumeDecisionChange} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), {
      target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` },
    });
    fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    await waitFor(() => expect(onRelativeVolumeDecisionChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ decisionId, decisionDigest: `sha256:${"a".repeat(64)}`, verdict: "ELIGIBLE" }),
    ));
    const callsAfterFirst = onRelativeVolumeDecisionChange.mock.calls.length;
    // Same id, new digest: the parent must hear the new decision, not keep the stale one.
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    fireEvent.click(await screen.findByRole("button", { name: "새 확인 요청 계속" }));
    await waitFor(() => expect(onRelativeVolumeDecisionChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ decisionId, decisionDigest: `sha256:${"b".repeat(64)}`, verdict: "ELIGIBLE" }),
    ));
    expect(onRelativeVolumeDecisionChange.mock.calls.length).toBeGreaterThan(callsAfterFirst);
    // 계약에 없는 판정(WITHDRAWN 등): 준비 완료가 아니라 모름으로 두고, 부모가
    // 가졌던 적격 권한은 null로 닫는다. 동결된 시도는 유지된다.
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    fireEvent.click(await screen.findByRole("button", { name: "새 확인 요청 계속" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    await waitFor(() => expect(onRelativeVolumeDecisionChange).toHaveBeenLastCalledWith(null));
    // No render loop: notifications settle once the server stops changing answers.
    const settled = onRelativeVolumeDecisionChange.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(onRelativeVolumeDecisionChange.mock.calls.length).toBe(settled);
  });
});

describe("evidence target-change and restart confirmation", () => {
  const otherTarget = {
    submissionRef: ref("e"),
    state: "SEALED" as const,
    submission: { revision: 1, artifacts: [{ artifactId: "dsm-2", kind: "dsm", fileName: "other.tif" }] },
  };
  type EvidencePost = { url: string; key: string; body: unknown };
  const scriptEvidence = (
    posts: EvidencePost[],
    script: { declarations: Array<"declared" | "fail" | "pending">; seals: Array<"ok" | "fail"> },
  ) => {
    let declarationCalls = 0;
    let sealCalls = 0;
    return async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence") && !init?.method) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/evidence") && init?.method === "POST") {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        posts.push({ url, key: headers["idempotency-key"], body });
        declarationCalls += 1;
        const step = script.declarations[declarationCalls - 1] ?? "declared";
        if (step === "pending") return new Promise(() => undefined);
        if (step === "fail") return { ok: false, status: 0, json: async () => ({}) };
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "DECLARED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"0".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: body.independenceBasis,
        });
      }
      if (url.endsWith("/upload-grant")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        posts.push({ url, key: headers["idempotency-key"], body: null });
        return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, uploadUrl: "https://upload.test/checkpoints", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
      }
      if (url === "https://upload.test/checkpoints") return response({});
      if (url.endsWith("/seal")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        posts.push({ url, key: headers["idempotency-key"], body: null });
        sealCalls += 1;
        const step = script.seals[sealCalls - 1] ?? "ok";
        if (step === "fail") return { ok: false, status: 0, json: async () => ({}) };
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "SEALED_BYTE_OBSERVED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"0".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "독립 측량",
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    };
  };

  const beginEvidenceDraft = async (label: RegExp, uuid: () => string) => {
    vi.stubGlobal("crypto", {
      randomUUID: uuid,
      subtle: { digest: async () => new Uint8Array(32).buffer },
    });
    fireEvent.click(await screen.findByRole("button", { name: label }));
    const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
    Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });
    fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
    fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
  };

  it("keeps the frozen attempt when the same target is reselected and sends no new request from selection", async () => {
    const posts: EvidencePost[] = [];
    fetchMock.mockImplementation(scriptEvidence(posts, { declarations: ["fail", "declared"], seals: ["ok"] }));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, otherTarget]} canWrite accountIdentity={fp()} />);
    await beginEvidenceDraft(/current\.tif/, () => "stable-evidence-key");
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    const postsAfterFailure = posts.length;

    // 같은 대상을 다시 눌러도 선택만으로 새 선언이 나가지 않고 동결이 유지된다.
    fireEvent.click(screen.getByRole("button", { name: /current\.tif/ }));
    expect(posts.length).toBe(postsAfterFailure);
    expect(screen.getByRole("button", { name: "다른 파일·선언으로 새로 시작" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("분석 시스템이 파일을 받았습니다. 측정 집계는 분석 시스템 기록 후 표시됩니다.")).toBeTruthy();
    const declarations = posts.filter((post) => post.url.endsWith("/evidence") && post.body !== null);
    expect(declarations).toHaveLength(2);
    expect(declarations[1].key).toBe(declarations[0].key);
    expect(declarations[1].body).toEqual(declarations[0].body);
  });

  it("preserves the frozen attempt across targets and offers an explicit return path", async () => {
    const posts: EvidencePost[] = [];
    fetchMock.mockImplementation(scriptEvidence(posts, { declarations: ["fail", "declared"], seals: ["ok"] }));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, otherTarget]} canWrite accountIdentity={fp()} />);
    await beginEvidenceDraft(/current\.tif/, () => "stable-evidence-key");
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    const postsAfterFailure = posts.length;

    // 다른 대상을 봐도 동결된 시도가 조용히 버려지지 않고, 선택만으로 새 선언이 나가지 않는다.
    fireEvent.click(screen.getByRole("button", { name: /other\.tif/ }));
    expect(posts.length).toBe(postsAfterFailure);
    expect(await screen.findByText(/다른 등록본에서 시작한/)).toBeTruthy();
    expect(await screen.findByText(/이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();

    // 원래 등록본으로 돌아가 같은 키·내용으로 재시도할 수 있다.
    fireEvent.click(screen.getByRole("button", { name: "원래 등록본으로 돌아가기" }));
    expect(screen.getByRole("button", { name: /current\.tif/ }).getAttribute("aria-current")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("분석 시스템이 파일을 받았습니다. 측정 집계는 분석 시스템 기록 후 표시됩니다.")).toBeTruthy();
    const declarations = posts.filter((post) => post.url.endsWith("/evidence") && post.body !== null);
    expect(declarations).toHaveLength(2);
    expect(declarations[1].key).toBe(declarations[0].key);
  });

  it("keeps an in-flight upload recoverable when the target changes", async () => {
    const posts: EvidencePost[] = [];
    let declarationSignal: AbortSignal | undefined;
    let declarationCalls = 0;
    const followUp = scriptEvidence(posts, { declarations: ["declared"], seals: ["ok"] });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence") && init?.method === "POST") {
        declarationCalls += 1;
        posts.push({ url, key: ((init.headers ?? {}) as Record<string, string>)["idempotency-key"], body: JSON.parse(String(init?.body)) });
        if (declarationCalls === 1) {
          declarationSignal = init.signal ?? undefined;
          return new Promise(() => undefined);
        }
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "DECLARED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"0".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "독립 측량",
        });
      }
      return followUp(url, init);
    });
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, otherTarget]} canWrite accountIdentity={fp()} />);
    await beginEvidenceDraft(/current\.tif/, () => "stable-evidence-key");
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    await waitFor(() => expect(declarationSignal).toBeDefined());

    fireEvent.click(screen.getByRole("button", { name: /other\.tif/ }));
    expect(declarationSignal?.aborted).toBe(true);
    expect(posts.filter((post) => post.body !== null)).toHaveLength(1);
    expect(await screen.findByText(/다른 등록본에서 시작한/)).toBeTruthy();

    // 중단된 시도는 같은 키로 다시 보낼 수 있다. 원래 문맥 밖에서 끝나므로
    // 성공 표시도 현재 선택이 아닌 원래 요청을 이름으로 밝힌다.
    fireEvent.click(screen.getByRole("button", { name: "같은 요청으로 다시 시도" }));
    expect(await screen.findByText(/원래 요청\(작업 current · 제출 1회차 · dsm\)의 증거를 분석 시스템이 받았습니다/)).toBeTruthy();
    const declarations = posts.filter((post) => post.url.endsWith("/evidence") && post.body !== null);
    expect(declarations).toHaveLength(2);
    expect(declarations[1].key).toBe(declarations[0].key);
  });

  it("requires an explicit informed confirmation before discarding an uncertain attempt", async () => {
    const posts: EvidencePost[] = [];
    let counter = 0;
    fetchMock.mockImplementation(scriptEvidence(posts, { declarations: ["fail", "declared"], seals: ["fail", "ok"] }));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await beginEvidenceDraft(/current\.tif/, () => `restart-key-${(counter += 1)}`);
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    const frozenKey = posts.filter((post) => post.body !== null)[0].key;
    const postsAfterFailure = posts.length;

    // 첫 클릭은 경고만 하고 해제하지 않는다 — 자동 변이가 없다.
    fireEvent.click(screen.getByRole("button", { name: "다른 파일·선언으로 새로 시작" }));
    expect(await screen.findByText(/이전 증거 요청이 이미 접수됐을 수 있습니다/)).toBeTruthy();
    expect(posts.length).toBe(postsAfterFailure);
    expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(true);

    // 유지하면 동결이 그대로 남는다.
    fireEvent.click(screen.getByRole("button", { name: "유지" }));
    expect(screen.queryByText(/이전 증거 요청이 이미 접수됐을 수 있습니다/)).toBeNull();
    expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(true);

    // 확인해야만 해제되고, 다음 제출은 새 키를 쓴다.
    fireEvent.click(screen.getByRole("button", { name: "다른 파일·선언으로 새로 시작" }));
    fireEvent.click(screen.getByRole("button", { name: "새로 시작 확인" }));
    expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량 2" } });
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    const declarations = posts.filter((post) => post.url.endsWith("/evidence") && post.body !== null);
    expect(declarations).toHaveLength(2);
    expect(declarations[1].key).not.toBe(frozenKey);
  });

  it("keeps the mismatch retry mutation inside the real laptop-only boundary and readable outside it", async () => {
    const posts: EvidencePost[] = [];
    fetchMock.mockImplementation(scriptEvidence(posts, { declarations: ["fail", "declared"], seals: ["ok"] }));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, otherTarget]} canWrite accountIdentity={fp()} />);
    await beginEvidenceDraft(/current\.tif/, () => "stable-evidence-key");
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /other\.tif/ }));
    expect(await screen.findByText(/다른 등록본에서 시작한/)).toBeTruthy();

    // 실제 경계를 목으로 지우지 않는다: 재시도 변이는 lg 전용 래퍼 안에 있고,
    // 모바일 안내는 같은 action으로 렌더된다. 알림 본문과 돌아가기는 바깥에 둔다.
    const retry = screen.getByRole("button", { name: "같은 요청으로 다시 시도" });
    const gated = retry.closest("div.hidden");
    expect(gated).not.toBeNull();
    expect(gated!.classList.contains("lg:contents")).toBe(true);
    const asides = document.querySelectorAll('[data-responsive-action-notice="EXTERNAL_RECONSTRUCTION_MUTATION"]');
    expect(asides.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/다른 등록본에서 시작한/).closest("div.hidden")).toBeNull();
    expect(screen.getByRole("button", { name: "원래 등록본으로 돌아가기" }).closest("div.hidden")).toBeNull();
    // 메모리 한계 경고는 경계 밖에 있어 모바일·읽기 전용에서도 보인다.
    // 기기 이동 시 같은 키 복구를 암시하지 않는다.
    expect(screen.getByText(/이 화면의 메모리에만 있습니다/).closest("div.hidden")).toBeNull();
    expect(screen.queryByText(/다른 기기로 이어집니다|다른 기기에서도 같은 요청/)).toBeNull();
    // 무조건적 중복 불가 단언은 없다: 동결된 키·내용·경로 재사용이라는
    // 좁은 사실과 분석 시스템 기록 확인만 말한다.
    expect(screen.queryByText(/다른 기록을 만들지 않습니다/)).toBeNull();
    expect(screen.getByText(/동결된 원래 키·내용·경로를 그대로 다시 보내며/)).toBeTruthy();
  });

  it("exposes no retry mutation to a read-only user while keeping return readable", async () => {
    const posts: EvidencePost[] = [];
    fetchMock.mockImplementation(scriptEvidence(posts, { declarations: ["fail", "declared"], seals: ["ok"] }));
    const view = render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, otherTarget]} canWrite accountIdentity={fp()} />);
    await beginEvidenceDraft(/current\.tif/, () => "stable-evidence-key");
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /other\.tif/ }));
    expect(await screen.findByText(/다른 등록본에서 시작한/)).toBeTruthy();
    const postsAfterFailure = posts.length;

    view.rerender(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, otherTarget]} canWrite={false} accountIdentity={fp()} />);
    expect(await screen.findByText(/다른 등록본에서 시작한/)).toBeTruthy();
    expect(screen.getByText(/이 화면의 메모리에만 있습니다/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "원래 등록본으로 돌아가기" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "같은 요청으로 다시 시도" })).toBeNull();
    expect(screen.queryByRole("button", { name: "파일 제출 마치기" })).toBeNull();
    expect(screen.getByText(/읽기 전용 화면에서는 다시 시도할 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/이 화면을 유지한 채 원래 계정의 쓰기 권한이 복원되면/)).toBeTruthy();

    // 읽기 전용의 돌아가기와 조회는 변이를 내지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "원래 등록본으로 돌아가기" }));
    expect(screen.getByRole("button", { name: /current\.tif/ }).getAttribute("aria-current")).toBe("true");
    expect(posts.length).toBe(postsAfterFailure);
  });

  it("names the frozen work/order/ref on a success completed outside the current selection", async () => {
    const posts: EvidencePost[] = [];
    fetchMock.mockImplementation(scriptEvidence(posts, { declarations: ["fail", "declared"], seals: ["ok"] }));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current, otherTarget]} canWrite accountIdentity={fp()} />);
    await beginEvidenceDraft(/current\.tif/, () => "stable-evidence-key");
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /other\.tif/ }));
    expect(await screen.findByText(/다른 등록본에서 시작한/)).toBeTruthy();

    // 원래 문맥이 아닌 곳에서 끝내도 현재 선택이 주인인 것처럼 보이지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "같은 요청으로 다시 시도" }));
    expect(await screen.findByText(/원래 요청\(작업 current · 제출 1회차 · dsm\)의 증거를 분석 시스템이 받았습니다/)).toBeTruthy();
    expect(await screen.findByText(/현재 선택한 등록본의 기록이 아니라 원래 요청의 기록을 확인하세요/)).toBeTruthy();
    const declarations = posts.filter((post) => post.url.endsWith("/evidence") && post.body !== null);
    expect(declarations).toHaveLength(2);
    expect(declarations[1].key).toBe(declarations[0].key);
    expect(declarations[1].url).toBe(declarations[0].url);
  });
});

describe("evidence account-continuity client guard", () => {
  type EvidenceCall = { url: string; key: string; continuity: string | null; body: unknown };
  const trackEvidence = (calls: EvidenceCall[], sealScript: Array<{ status: number; code?: string }>) =>
    async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence") && !init?.method) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/evidence") && init?.method === "POST") {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        calls.push({ url, key: headers["idempotency-key"], continuity: headers["x-ksi-continuity-fingerprint"] ?? null, body: JSON.parse(String(init?.body)) });
        const step = calls.filter((call) => call.url.endsWith("/evidence") && !call.url.includes("/upload-grant") && !call.url.includes("/seal")).length;
        void step;
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "DECLARED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"0".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: (JSON.parse(String(init?.body)) as { independenceBasis: string }).independenceBasis,
        });
      }
      if (url.endsWith("/upload-grant")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        calls.push({ url, key: headers["idempotency-key"], continuity: headers["x-ksi-continuity-fingerprint"] ?? null, body: null });
        return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, uploadUrl: "https://upload.test/checkpoints", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
      }
      if (url === "https://upload.test/checkpoints") return response({});
      if (url.endsWith("/seal")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        calls.push({ url, key: headers["idempotency-key"], continuity: headers["x-ksi-continuity-fingerprint"] ?? null, body: null });
        const sealCalls = calls.filter((call) => call.url.endsWith("/seal")).length;
        const step = sealScript[sealCalls - 1] ?? { status: 201 };
        if (step.status === 201) {
          return response({
            evidenceRef: `eev-v1-${"a".repeat(64)}`,
            state: "SEALED_BYTE_OBSERVED",
            targetDsmArtifactId: "dsm",
            declaredContentDigest: `sha256:${"0".repeat(64)}`,
            declaredContentType: "text/csv",
            independenceBasis: "독립 측량",
          });
        }
        if (step.status === 0) return { ok: false, status: 0, json: async () => ({}) };
        return { ok: false, status: step.status, json: async () => (step.code ? { code: step.code } : {}) };
      }
      throw new Error(`unexpected fetch ${url}`);
    };

  const startEvidenceDraft = async () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "stable-evidence-key",
      subtle: { digest: async () => new Uint8Array(32).buffer },
    });
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
    Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });
    fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
    fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
  };

  it("sends the frozen continuity fingerprint on declaration, grant and seal and reuses the frozen key/body/path on retry", async () => {
    const calls: EvidenceCall[] = [];
    fetchMock.mockImplementation(trackEvidence(calls, [{ status: 0 }, { status: 201 }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await startEvidenceDraft();
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();

    const first = calls.filter((call) => !call.url.includes("/upload-grant") && !call.url.includes("/seal"));
    const firstGrant = calls.find((call) => call.url.endsWith("/upload-grant"));
    const firstSeal = calls.find((call) => call.url.endsWith("/seal"));
    expect(first).toHaveLength(1);
    expect(firstGrant).toBeTruthy();
    expect(firstSeal).toBeTruthy();
    // 같은 화면 복구에는 세 단계 모두 첫 신원의 비교값을 그대로 싣는다.
    expect(first[0].continuity).toBe(fp().fingerprint);
    expect(firstGrant?.continuity).toBe(fp().fingerprint);
    expect(firstSeal?.continuity).toBe(fp().fingerprint);

    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("분석 시스템이 파일을 받았습니다. 측정 집계는 분석 시스템 기록 후 표시됩니다.")).toBeTruthy();
    const declarations = calls.filter((call) => call.url.endsWith("/evidence") && call.body !== null);
    expect(declarations).toHaveLength(2);
    expect(declarations[1].key).toBe(declarations[0].key);
    expect(declarations[1].body).toEqual(declarations[0].body);
    expect(declarations[1].url).toBe(declarations[0].url);
    expect(declarations[1].continuity).toBe(fp().fingerprint);
    const seals = calls.filter((call) => call.url.endsWith("/seal"));
    expect(seals[1].key).toBe(seals[0].key);
    expect(seals[1].continuity).toBe(fp().fingerprint);
  });

  it("blocks a new evidence declaration without a bound identity but keeps the frozen retry", async () => {
    const calls: EvidenceCall[] = [];
    fetchMock.mockImplementation(trackEvidence(calls, [{ status: 0 }, { status: 201 }]));
    const view = render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite />);
    await startEvidenceDraft();
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect((await screen.findAllByText(/계정을 확인하지 못해 새 증거 선언을 시작할 수 없습니다/)).length).toBeGreaterThanOrEqual(1);
    expect(calls.filter((call) => call.body !== null)).toHaveLength(0);

    // 같은 화면에서 계정이 돌아오면 같은 파일·선언으로 새로 시작할 수 있다.
    view.rerender(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    expect(calls.filter((call) => call.body !== null)).toHaveLength(1);

    // 세션이 바뀌어 비교값을 잃어도 동결된 재시도는 같은 키·내용·연속성으로 이어간다.
    view.rerender(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("분석 시스템이 파일을 받았습니다. 측정 집계는 분석 시스템 기록 후 표시됩니다.")).toBeTruthy();
    const declarations = calls.filter((call) => call.body !== null);
    expect(declarations).toHaveLength(2);
    expect(declarations[1].key).toBe(declarations[0].key);
    expect(declarations[1].continuity).toBe(fp().fingerprint);
  });

  it("keeps the frozen evidence request on an account-continuity block and does not claim a rejection", async () => {
    const calls: EvidenceCall[] = [];
    fetchMock.mockImplementation(trackEvidence(calls, [{ status: 0 }, { status: 409, code: "ACCOUNT_CONTINUITY_MISMATCH" }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await startEvidenceDraft();
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    const frozenKey = calls.filter((call) => call.body !== null)[0].key;

    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText(/계정이 바뀌어 같은 증거 요청을 다시 보내지 않았습니다/)).toBeTruthy();
    expect(await screen.findByText(/이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();
    const declarations = calls.filter((call) => call.body !== null);
    expect(declarations).toHaveLength(2);
    expect(declarations[1].key).toBe(frozenKey);
    // 동결된 입력은 그대로 남아 다시 시도할 수 있다.
    expect(screen.getByRole("button", { name: "다른 파일·선언으로 새로 시작" })).toBeTruthy();
  });

  it("halts before upload and seal when the session changes after a successful retry declaration (grant-stage block)", async () => {
    // 화면 연쇄 테스트. fetch mock은 BFF 경계다 — 실제 세션 교체가 아니다.
    // 재현하는 흐름: 1차 시도의 grant 응답 유실(모호) → 같은 키 재시도의 선언
    // replay는 아직 A 세션에서 성공 → grant 직전에 세션이 B로 전환 → BFF가
    // grant 단계에서 409. 재시도 시작 전에 이미 B였다면 선언 가드가 먼저
    // 막으므로, 그 경우는 이 테스트가 주장하지 않는다.
    let declareBody: Record<string, unknown> | null = null;
    const declareKeys: string[] = [];
    const grantKeys: string[] = [];
    let grantCalls = 0;
    let putCalls = 0;
    let sealCalls = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence") && !init?.method) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/evidence") && init?.method === "POST") {
        const headers = (init.headers ?? {}) as Record<string, string>;
        declareKeys.push(headers["idempotency-key"]);
        declareBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "DECLARED",
          targetDsmArtifactId: declareBody.targetDsmArtifactId,
          declaredContentDigest: declareBody.declaredContentDigest,
          declaredContentType: declareBody.declaredContentType,
          independenceBasis: declareBody.independenceBasis,
        });
      }
      if (url.endsWith("/upload-grant")) {
        grantCalls += 1;
        grantKeys.push(((init?.headers ?? {}) as Record<string, string>)["idempotency-key"]);
        if (grantCalls === 1) throw new Error("grant response lost");
        if (grantCalls === 2) return { ok: false, status: 409, json: async () => ({ code: "ACCOUNT_CONTINUITY_MISMATCH" }) };
        return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, uploadUrl: "https://upload.test/checkpoints", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
      }
      if (url === "https://upload.test/checkpoints") {
        putCalls += 1;
        return response({});
      }
      if (url.endsWith("/seal")) {
        sealCalls += 1;
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "SEALED_BYTE_OBSERVED",
          targetDsmArtifactId: (declareBody as Record<string, unknown>).targetDsmArtifactId,
          declaredContentDigest: (declareBody as Record<string, unknown>).declaredContentDigest,
          declaredContentType: (declareBody as Record<string, unknown>).declaredContentType,
          independenceBasis: (declareBody as Record<string, unknown>).independenceBasis,
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal("crypto", {
      randomUUID: () => "stable-grant-stage-key",
      subtle: { digest: async () => new Uint8Array(32).buffer },
    });
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
    const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
    Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });
    fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
    fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });

    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    expect(grantCalls).toBe(1);
    expect(putCalls).toBe(0);
    expect(sealCalls).toBe(0);

    // 선언 replay는 A로 성공하고, grant에서 BFF가 계정 전환을 끊는다.
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    const blocked = await screen.findByText(/계정이 바뀌어 같은 증거 요청을 다시 보내지 않았습니다/);
    expect(blocked.getAttribute("role")).toBe("alert");
    expect(blocked.textContent).toContain("(파일 업로드 승인 단계)");
    expect(blocked.textContent).toContain("이전 요청이 처리되었는지는 알 수 없습니다");
    expect(grantCalls).toBe(2);
    expect(putCalls).toBe(0);
    expect(sealCalls).toBe(0);
    expect(new Set(declareKeys).size).toBe(1);
    expect(new Set(grantKeys).size).toBe(1);

    // 원래 계정으로 돌아오면 같은 키로 봉인까지 이어간다.
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("분석 시스템이 파일을 받았습니다. 측정 집계는 분석 시스템 기록 후 표시됩니다.")).toBeTruthy();
    expect(new Set(declareKeys).size).toBe(1);
    expect(new Set(grantKeys).size).toBe(1);
    expect(putCalls).toBe(1);
    expect(sealCalls).toBe(1);
  });
});

describe("decision frozen path, response binding, and read-only discoverability", () => {
  type DecisionCall = { url: string; key: string; continuity: string | null; body: unknown };
  const trackDecisions = (
    calls: DecisionCall[],
    steps: Array<{ status: number; decision?: unknown; code?: string }>,
  ) =>
    async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence")) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") {
        return response({ workAreas: [{ workAreaId: "pile-1", name: "야적장 1", status: "ACTIVE" }, { workAreaId: "area-1", name: "A구역", status: "ACTIVE" }] });
      }
      if (url === "/api/sites/site-1/observation-work-orders") {
        return response({
          workOrders: [
            { workOrderId: "current", name: "현재 작업", cycleNumber: 1 },
            { workOrderId: "other", name: "다른 작업", cycleNumber: 2 },
          ],
        });
      }
      if (url === "/api/observation-work-orders/current/external-reconstruction-submissions") {
        return response({ submissions: [current, sameWorkOrderBaseline] });
      }
      if (url === "/api/observation-work-orders/other/external-reconstruction-submissions") {
        return response({ submissions: [otherWorkOrderBaseline] });
      }
      if (url.includes("/use-decisions/")) {
        const headers = (init?.headers ?? {}) as Record<string, string>;
        calls.push({ url, key: headers["idempotency-key"], continuity: headers["x-ksi-continuity-fingerprint"] ?? null, body: init?.body ? JSON.parse(String(init.body)) : null });
        const step = steps[calls.length - 1] ?? { status: 201 };
        if (step.status === 201) return response({ decision: step.decision });
        if (step.status === 0) return { ok: false, status: 0, json: async () => ({}) };
        return { ok: false, status: step.status, json: async () => (step.code ? { code: step.code } : {}) };
      }
      throw new Error(`unexpected fetch ${url}`);
    };
  const contractDecision = (use: string, verdict: string, id = "d", extra: Record<string, unknown> = {}) => ({
    decisionId: `external-use-decision-${id.repeat(32)}`,
    decisionDigest: `sha256:${id.repeat(64)}`,
    subject: contractSubject("current", 1, "sub-current-1"),
    subjectDigest: `sha256:${"e".repeat(64)}`,
    use,
    verdict,
    reasons: [],
    remediations: [],
    decidedAt: "2026-09-09T00:00:00Z",
    ...extra,
  });
  const selectCurrentTarget = async () => {
    fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
  };

  it("posts a frozen decision retry to the original work-order path after props change", async () => {
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 0 }, { status: 0 }]));
    const view = render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();

    // 같은 화면이 다른 작업 속성으로 바뀌어도 동결된 같은 키·내용은 원래 경로로만 나간다.
    view.rerender(<ExternalEvidencePanel workOrderId="other-work" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].url).toBe(calls[0].url);
    expect(calls[1].url).toContain("/observation-work-orders/current/");
    expect(calls[1].key).toBe(calls[0].key);
    expect(calls[1].body).toEqual(calls[0].body);
  });

  it("stops feeding the parent volume issue path when the work-order context changes", async () => {
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: {
      ...contractDecision("RELATIVE_VOLUME", "RESTRICTED", "a"),
      baselineSubject: contractSubject("current", 2, "sub-baseline-2"),
      baselineSubjectDigest: `sha256:${"e".repeat(64)}`,
      currentSubject: contractSubject("current", 1, "sub-current-1"),
      currentSubjectDigest: `sha256:${"f".repeat(64)}`,
      zone: contractZone("area-1"),
    } }]));
    const onRelativeVolumeDecisionChange = vi.fn();
    const view = render(
      <ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} onRelativeVolumeDecisionChange={onRelativeVolumeDecisionChange} />,
    );
    await selectCurrentTarget();
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 변화 분석/)).toBeTruthy();
    expect(onRelativeVolumeDecisionChange).toHaveBeenLastCalledWith(expect.objectContaining({ verdict: "RESTRICTED" }));
    expect(calls).toHaveLength(1);

    // 문맥이 바뀌면 새 요청 없이 부모 발급도 fail-closed로 닫는다.
    view.rerender(
      <ExternalEvidencePanel workOrderId="other-work" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} onRelativeVolumeDecisionChange={onRelativeVolumeDecisionChange} />,
    );
    await waitFor(() => expect(onRelativeVolumeDecisionChange).toHaveBeenLastCalledWith(null));
    expect(calls).toHaveLength(1);
  });

  it.each([
    { name: "single-use mismatch", button: "화면 표시 다시 확인", decision: { use: "HEIGHT", verdict: "ELIGIBLE" } },
  ])("does not mark an unbound $name response as ready", async ({ button, decision }) => {
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: { ...contractDecision("DISPLAY", "ELIGIBLE"), ...decision } }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.click(screen.getByRole("button", { name: button }));
    // 다른 용도·알 수 없는 판정은 준비 완료가 아니라 모름으로 둔다.
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정/)).toBeNull();
    expect(calls).toHaveLength(1);
    const frozenKey = calls[0].key;
    fireEvent.click(screen.getByRole("button", { name: button }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].key).toBe(frozenKey);
  });

  it("does not mark a non-contract verdict as ready", async () => {
    // 생산 계약 판정 집합(ELIGIBLE/RESTRICTED/BLOCKED) 밖의 2xx는 준비 완료가
    // 아니라 모름으로 둔다. 동결된 시도는 유지된다.
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: contractDecision("DISPLAY", "PENDING") }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정/)).toBeNull();
    expect(calls).toHaveLength(1);
  });

  it("does not mark a 2xx without a decision id as ready", async () => {
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: { use: "DISPLAY", verdict: "ELIGIBLE" } }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정/)).toBeNull();
    expect(calls).toHaveLength(1);
  });

  it("rejects a same-use pair decision whose baseline subject is bound to another site", async () => {
    // 동결 siteId는 두 subject 모두의 실제 증인이다(현장 범위 목록에서 얼리고,
    // Core도 쌍의 조직·현장 일치를 강제한다). 기준만 다른 현장이면 같은
    // workOrderId·revision이라도 현재 요청의 권한이 될 수 없다.
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: {
      ...contractDecision("RELATIVE_VOLUME", "ELIGIBLE", "a"),
      baselineSubject: contractSubject("current", 2, "sub-baseline-2", "site-2"),
      baselineSubjectDigest: `sha256:${"e".repeat(64)}`,
      currentSubject: contractSubject("current", 1, "sub-current-1"),
      currentSubjectDigest: `sha256:${"f".repeat(64)}`,
      zone: contractZone("area-1"),
    } }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정: 변화 분석/)).toBeNull();
    expect(calls).toHaveLength(1);
    const frozenKey = calls[0].key;
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].key).toBe(frozenKey);
    expect(calls[1].body).toEqual(calls[0].body);
  });

  it("rejects a same-use pair decision whose subjects disagree on organization", async () => {
    // 조직 증인은 따로 얼리지 않으므로, 둘 다 원문으로 있을 때만 서로 대조한다.
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: {
      ...contractDecision("RELATIVE_VOLUME", "ELIGIBLE", "a"),
      baselineSubject: contractSubject("current", 2, "sub-baseline-2", "site-1", "org-b"),
      baselineSubjectDigest: `sha256:${"e".repeat(64)}`,
      currentSubject: contractSubject("current", 1, "sub-current-1", "site-1", "org-a"),
      currentSubjectDigest: `sha256:${"f".repeat(64)}`,
      zone: contractZone("area-1"),
    } }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정: 변화 분석/)).toBeNull();
    expect(calls).toHaveLength(1);
  });

  it.each([{ field: "reasons" }, { field: "remediations" }])("rejects a decision with non-string $field entries", async ({ field }) => {
    // 표시·부모 전달 전에 join되므로 문자열이 아니면 모름으로 둔다.
    const calls: DecisionCall[] = [];
    const malformed = { ...contractDecision("DISPLAY", "ELIGIBLE"), [field]: ["HISTORICAL", 42] };
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: malformed }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정/)).toBeNull();
    expect(calls).toHaveLength(1);
  });

  it("recovers a frozen attempt with a real-contract-shaped pair decision on retry", async () => {
    // 모호한 첫 시도 뒤 같은 키 재시도가 계약 형태 그대로 오면 준비 완료가 되고,
    // 부모 발급 경로에 원래 요청의 판정이 전달된다.
    const calls: DecisionCall[] = [];
    const valid = {
      ...contractDecision("RELATIVE_VOLUME", "ELIGIBLE", "a"),
      baselineSubject: contractSubject("current", 2, "sub-baseline-2"),
      baselineSubjectDigest: `sha256:${"e".repeat(64)}`,
      currentSubject: contractSubject("current", 1, "sub-current-1"),
      currentSubjectDigest: `sha256:${"f".repeat(64)}`,
      zone: contractZone("area-1"),
    };
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 0 }, { status: 201, decision: valid }]));
    const onRelativeVolumeDecisionChange = vi.fn();
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} onRelativeVolumeDecisionChange={onRelativeVolumeDecisionChange} />);
    await selectCurrentTarget();
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
    expect(await screen.findByText(/현재 분석 시스템 판정: 변화 분석/)).toBeTruthy();
    expect(calls).toHaveLength(2);
    expect(calls[1].key).toBe(calls[0].key);
    expect(calls[1].body).toEqual(calls[0].body);
    expect(onRelativeVolumeDecisionChange).toHaveBeenLastCalledWith(expect.objectContaining({ verdict: "ELIGIBLE" }));
  });

  it("rejects a single-volume response bound to another use", async () => {
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: contractDecision("DISPLAY", "ELIGIBLE") }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    await waitFor(() => expect(screen.getByLabelText("한 시점 측정 구역").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("한 시점 측정 구역"), { target: { value: "pile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "한 시점 측정 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정: 한 시점 측정/)).toBeNull();
  });

  it("rejects a pair response bound to another use", async () => {
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 201, decision: {
      ...contractDecision("DISPLAY", "ELIGIBLE"),
      baselineSubject: contractSubject("current", 2, "sub-baseline-2"),
      baselineSubjectDigest: `sha256:${"e".repeat(64)}`,
      currentSubject: contractSubject("current", 1, "sub-current-1"),
      currentSubjectDigest: `sha256:${"f".repeat(64)}`,
    } }]));
    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option")).toHaveLength(3));
    fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), { target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` } });
    fireEvent.click(screen.getByRole("button", { name: "눈으로 비교 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText(/현재 분석 시스템 판정: 눈으로 비교/)).toBeNull();
  });

  it("keeps a same-id seal with different content unconfirmed and retains the frozen evidence", async () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "stable-key",
      subtle: { digest: async () => new Uint8Array(32).buffer },
    });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence") && !init?.method) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/evidence") && init?.method === "POST") {
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "DECLARED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"0".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "독립 측량",
        });
      }
      if (url.endsWith("/upload-grant")) return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, uploadUrl: "https://upload.test/checkpoints", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
      if (url === "https://upload.test/checkpoints") return response({});
      if (url.endsWith("/seal")) {
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "SEALED_BYTE_OBSERVED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"f".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "독립 측량",
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
    Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });

    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
    fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    // 같은 식별자라도 내용이 다르면 봉인 확정으로 두지 않고 모름으로 둔다.
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "다른 파일·선언으로 새로 시작" })).toBeTruthy();
  });

  it("keeps a same-id seal with missing content fields unconfirmed", async () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "stable-key",
      subtle: { digest: async () => new Uint8Array(32).buffer },
    });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence") && !init?.method) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/evidence") && init?.method === "POST") {
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "DECLARED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"0".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "독립 측량",
        });
      }
      if (url.endsWith("/upload-grant")) return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, uploadUrl: "https://upload.test/checkpoints", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
      if (url === "https://upload.test/checkpoints") return response({});
      if (url.endsWith("/seal")) {
        return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, state: "SEALED_BYTE_OBSERVED" });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
    Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });

    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
    fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(true);
  });

  it("clears a fully content-bound seal response", async () => {
    vi.stubGlobal("crypto", {
      randomUUID: () => "stable-key",
      subtle: { digest: async () => new Uint8Array(32).buffer },
    });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence") && !init?.method) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/evidence") && init?.method === "POST") {
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "DECLARED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"0".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "독립 측량",
        });
      }
      if (url.endsWith("/upload-grant")) return response({ evidenceRef: `eev-v1-${"a".repeat(64)}`, uploadUrl: "https://upload.test/checkpoints", expiresAt: "2030-01-01T00:00:00Z", requiredHeaders: {} });
      if (url === "https://upload.test/checkpoints") return response({});
      if (url.endsWith("/seal")) {
        return response({
          evidenceRef: `eev-v1-${"a".repeat(64)}`,
          state: "SEALED_BYTE_OBSERVED",
          targetDsmArtifactId: "dsm",
          declaredContentDigest: `sha256:${"0".repeat(64)}`,
          declaredContentType: "text/csv",
          independenceBasis: "독립 측량",
        });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
    Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });

    render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
    fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("분석 시스템이 파일을 받았습니다. 측정 집계는 분석 시스템 기록 후 표시됩니다.")).toBeTruthy();
    expect((screen.getByLabelText("독립 검사점 CSV") as HTMLInputElement).disabled).toBe(false);
  });

  it("keeps a frozen evidence attempt discoverable without a write when read-only on the same target", async () => {
    const calls: DecisionCall[] = [];
    vi.stubGlobal("crypto", {
      randomUUID: () => "stable-key",
      subtle: { digest: async () => new Uint8Array(32).buffer },
    });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence") && !init?.method) return response({ items: [] });
      if (url === "/api/sites/site-1/work-areas") return response({ workAreas: [] });
      if (url === "/api/sites/site-1/observation-work-orders") return response({ workOrders: [] });
      if (url.endsWith("/evidence") && init?.method === "POST") {
        calls.push({ url, key: "", continuity: null, body: null });
        return { ok: false, status: 0, json: async () => ({}) };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    const checkpoint = new File(["x,y,z"], "checkpoints.csv", { type: "text/csv" });
    Object.defineProperty(checkpoint, "arrayBuffer", { value: async () => new Uint8Array([1]).buffer });
    const view = render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.change(screen.getByLabelText("독립 검사점 CSV"), { target: { files: [checkpoint] } });
    fireEvent.change(screen.getByLabelText("독립성 근거 선언"), { target: { value: "독립 측량" } });
    fireEvent.click(screen.getByRole("button", { name: "파일 제출 마치기" }));
    expect(await screen.findByText("증거 전송 상태를 확인하지 못했습니다. 같은 파일과 선언으로 재시도합니다.")).toBeTruthy();
    const postsAfterFailure = calls.length;

    view.rerender(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite={false} accountIdentity={fp()} />);
    expect(await screen.findByText(/전송 상태를 확인하지 못한 증거 요청이 있습니다/)).toBeTruthy();
    expect(await screen.findByText(/이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/이 화면을 유지한 채 원래 계정의 쓰기 권한이 복원되면/)).toBeTruthy();
    expect(screen.getByText(/새로고침·화면 이동·기기 변경 시 이 화면의 요청은 사라집니다/)).toBeTruthy();
    expect(screen.queryByText(/쓰기 권한으로 화면을 다시 열면/)).toBeNull();
    expect(screen.queryByRole("button", { name: "같은 요청으로 다시 시도" })).toBeNull();
    expect(screen.queryByRole("button", { name: "파일 제출 마치기" })).toBeNull();
    expect(screen.queryByRole("button", { name: "다른 파일·선언으로 새로 시작" })).toBeNull();
    expect(calls.length).toBe(postsAfterFailure);
  });

  it("keeps an unresolved decision discoverable without a write when read-only", async () => {
    const calls: DecisionCall[] = [];
    fetchMock.mockImplementation(trackDecisions(calls, [{ status: 0 }]));
    const view = render(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite accountIdentity={fp()} />);
    await selectCurrentTarget();
    fireEvent.click(screen.getByRole("button", { name: "화면 표시 다시 확인" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();

    view.rerender(<ExternalEvidencePanel workOrderId="current" siteId="site-1" revisions={[current]} canWrite={false} accountIdentity={fp()} />);
    expect(await screen.findByText(/확인하지 못한 사용 결정 요청이 있습니다/)).toBeTruthy();
    expect(screen.getByText(/이 화면을 유지한 채 원래 계정의 쓰기 권한이 복원되면/)).toBeTruthy();
    expect(screen.getByText(/새로고침·화면 이동·기기 변경 시 이 화면의 요청은 사라집니다/)).toBeTruthy();
    expect(screen.queryByText(/쓰기 권한으로 화면을 다시 열면/)).toBeNull();
    expect(screen.queryByRole("button", { name: "화면 표시 다시 확인" })).toBeNull();
    expect(calls).toHaveLength(1);
  });
});
