// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { ExternalReconstructionPanel } from "@/app/field/ExternalReconstructionPanel";

const ref = (character: string) => `ers-v1-${character.repeat(64)}`;
const digest = (character: string) => `sha256:${character.repeat(64)}`;
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
    artifacts: [{ artifactId: "dsm", kind: "dsm", fileName: "other-work-order.tif" }],
  },
};

const fetchMock = vi.fn();
function response(value: unknown, ok = true) {
  return { ok, json: async () => value };
}
class FakeWorker {
  static instances: FakeWorker[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  terminate = vi.fn();
  constructor() { FakeWorker.instances.push(this); }
  postMessage(request: { id: string }) { void request; }
}

function sealedInspection() {
  return response({
    registrationState: "SEALED",
    sealState: "SEALED",
    inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null },
    display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-display", receiptDigest: digest("d") },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("Worker", FakeWorker);
  let keySeq = 0;
  vi.stubGlobal("crypto", { randomUUID: () => `parent-wiring-key-${++keySeq}` });
  FakeWorker.instances = [];
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

/**
 * Composed real parent → real child → real workflow integration.
 * The evidence panel is the real component (not a vi.fn stub): a RELATIVE_VOLUME
 * decision is requested through its real UI, the real parent receiver forwards it,
 * and the real workflow panel issues with it. This proves the composed flow does
 * not enter a render/effect loop and does not retain a stale decision.
 *
 * Notification-key note: the BFF accepts only `{ decisionRef }` (exact keys;
 * see relative-volume-requests/route.ts) and Core revalidates id+digest
 * server-side against immutable journal records, so `decisionId|decisionDigest`
 * covers every field that can legitimately affect issuance.
 */
describe("parent decision wiring (real parent + real child + real workflow)", () => {
  it("reaches the workflow issue button, survives a draft change without a new POST, and restores the exact issuance with the same key", async () => {
    const errors: string[] = [];
    const onError = (event: ErrorEvent) => { errors.push(String(event.error ?? event.message)); };
    window.addEventListener("error", onError);
    try {
      const posts: Array<{ key: string; body: unknown }> = [];
      let resolveFirst: ((value: unknown) => void) | undefined;
      let attempts = 0;
      fetchMock.mockImplementation((url: string, init?: RequestInit) => {
        if (url.endsWith("/evidence")) return Promise.resolve(response({ items: [] }));
        if (url === "/api/sites/site-1/work-areas") {
          return Promise.resolve(response({ workAreas: [{ workAreaId: "area-1", name: "A구역", status: "ACTIVE" }, { workAreaId: "area-2", name: "B구역", status: "ACTIVE" }] }));
        }
        if (url === "/api/sites/site-1/observation-work-orders") {
          return Promise.resolve(response({
            workOrders: [
              { workOrderId: "current", name: "현재 작업", cycleNumber: 1 },
              { workOrderId: "other", name: "기준 작업", cycleNumber: 2 },
            ],
          }));
        }
        if (url === "/api/observation-work-orders/current/external-reconstruction-submissions" && !init?.method) {
          return Promise.resolve(response({ submissions: [current, sameWorkOrderBaseline] }));
        }
        if (url === "/api/observation-work-orders/other/external-reconstruction-submissions" && !init?.method) {
          return Promise.resolve(response({ submissions: [otherWorkOrderBaseline] }));
        }
        if (url.endsWith("/inspection")) return Promise.resolve(sealedInspection());
        if (url.endsWith("/use-decisions/pair")) {
          const body = JSON.parse(String(init?.body)) as { use: string; baselineWorkOrderId: string; baselineRevision: number; zoneId?: string };
          const tag = String(body.use)[0];
          return Promise.resolve(response({
            decision: {
              decisionId: `external-use-decision-${tag.repeat(32)}`,
              decisionDigest: digest(tag),
              baselineSubject: { organizationId: "org-1", siteId: "site-1", workOrderId: body.baselineWorkOrderId, submissionId: "sub-baseline-x", revision: body.baselineRevision, submissionDigest: digest("c"), manifestDigest: digest("d") },
              baselineSubjectDigest: digest("e"),
              currentSubject: { organizationId: "org-1", siteId: "site-1", workOrderId: "current", submissionId: "sub-current-1", revision: 1, submissionDigest: digest("c"), manifestDigest: digest("d") },
              currentSubjectDigest: digest("f"),
              use: body.use,
              ...(body.use === "RELATIVE_VOLUME" ? { zone: { zoneId: body.zoneId ?? "area-1", revision: 3, definitionDigest: digest("2"), observedCrsDigest: digest("3"), observedVerticalReferenceDigest: digest("4") } } : {}),
              verdict: "ELIGIBLE",
              reasons: [],
              remediations: [],
              decidedAt: "2026-09-09T00:00:00Z",
            },
          }));
        }
        if (url.endsWith("/use-decisions/single")) {
          return Promise.resolve(response({
            decision: {
              decisionId: `external-use-decision-${"s".repeat(32)}`,
              decisionDigest: digest("s"),
              subject: { organizationId: "org-1", siteId: "site-1", workOrderId: "current", submissionId: "sub-current-1", revision: 1, submissionDigest: digest("c"), manifestDigest: digest("d") },
              subjectDigest: digest("e"),
              use: "DISPLAY",
              verdict: "ELIGIBLE",
              reasons: [],
              remediations: [],
              decidedAt: "2026-09-09T00:00:00Z",
            },
          }));
        }
        if (url === "/api/observation-work-orders/current/relative-volume-requests" && !init?.method) {
          return Promise.resolve(response({ items: [] }));
        }
        if (url === "/api/observation-work-orders/current/relative-volume-requests" && init?.method === "POST") {
          attempts += 1;
          const headers = (init.headers as Record<string, string>) ?? {};
          posts.push({ key: headers["idempotency-key"], body: JSON.parse(String(init?.body)) });
          if (attempts === 1) return new Promise((resolve) => { resolveFirst = resolve as (value: unknown) => void; });
          return Promise.resolve(response({
            verdict: "ISSUED",
            request: { requestRef: `external-relative-volume-${"e".repeat(32)}`, status: "QUEUED", reportRef: null },
            detail: null,
          }));
        }
        if (url.includes("/single-volume-requests")) return Promise.resolve(response({ items: [] }));
        if (url.includes("/observation-work-orders") && !init?.method) return Promise.resolve(response({ workOrders: [] }));
        throw new Error(`unexpected fetch ${url}`);
      });

      const { rerender } = render(
        <ExternalReconstructionPanel workOrderId="current" siteId="site-1" expectedEpochId="epoch-1" canWrite permissions={["SITES_WRITE"]} accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />,
      );

      // Drive the real evidence UI to a READY relative-volume decision.
      fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
      await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option").length).toBeGreaterThan(1));
      fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), {
        target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` },
      });
      fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
      fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));

      // The real parent receiver forwards the ELIGIBLE decision to the real workflow.
      const issueButton = await screen.findByRole("button", { name: "상대 물량 비교 요청" });
      expect(issueButton).toBeTruthy();

      // Quiescence: a same-props rerender must not refetch or notify in a loop.
      const callsBefore = fetchMock.mock.calls.length;
      rerender(
        <ExternalReconstructionPanel workOrderId="current" siteId="site-1" expectedEpochId="epoch-1" canWrite permissions={["SITES_WRITE"]} accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />,
      );
      await waitFor(() => expect(screen.getByRole("button", { name: "상대 물량 비교 요청" })).toBeTruthy());
      expect(fetchMock.mock.calls.length).toBe(callsBefore);
      expect(errors.filter((message) => message.includes("Maximum update depth"))).toHaveLength(0);

      // Issue; the first POST stays in flight.
      fireEvent.click(screen.getByRole("button", { name: "상대 물량 비교 요청" }));
      await waitFor(() => expect(posts).toHaveLength(1));
      const firstKey = posts[0].key;
      expect(posts[0].body).toEqual({ decisionRef: `external-use-decision-${"R".repeat(32)}` });

      // Draft change: switch the zone. No new POST, no abort of the in-flight
      // issue; the retained attempt surfaces as an orphan banner, not a new key.
      fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-2" } });
      expect(await screen.findByText(/이전 상대 물량 비교 요청의 결과를 확인하지 못했습니다/)).toBeTruthy();
      expect(posts).toHaveLength(1);

      // The late first response binds to the live selection: it must not
      // auto-select into the changed draft.
      resolveFirst!(response({
        verdict: "ISSUED",
        request: { requestRef: `external-relative-volume-${"e".repeat(32)}`, status: "QUEUED", reportRef: null },
        detail: null,
      }));
      await waitFor(() => expect(screen.getByText(/접수되었습니다. 현재 선택과 다른 조건의 요청이므로 목록에서 확인하세요/)).toBeTruthy());
      expect(posts).toHaveLength(1);

      // Return to the original draft: the retained attempt replays the same key.
      fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
      await waitFor(() => expect(screen.queryByText(/이전 상대 물량 비교 요청의 결과를 확인하지 못했습니다/)).toBeNull());
      fireEvent.click(await screen.findByRole("button", { name: "상대 물량 비교 요청" }));
      await waitFor(() => expect(posts).toHaveLength(2));
      expect(posts[1].key).toBe(firstKey);
      expect(posts[1].body).toEqual(posts[0].body);
      expect(await screen.findByText("외부 상대 물량 비교를 요청했습니다.")).toBeTruthy();

      expect(errors.filter((message) => message.includes("Maximum update depth"))).toHaveLength(0);
    } finally {
      window.removeEventListener("error", onError);
    }
  });

  it("treats a changed digest as a new decision and blocks a lost verdict through the real parent", async () => {
    const decisionId = `external-use-decision-${"c".repeat(32)}`;
    const posts: Array<{ key: string; body: unknown }> = [];
    let pairCalls = 0;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/evidence")) return Promise.resolve(response({ items: [] }));
      if (url === "/api/sites/site-1/work-areas") {
        return Promise.resolve(response({ workAreas: [
          { workAreaId: "area-1", name: "A구역", status: "ACTIVE" },
          { workAreaId: "area-2", name: "B구역", status: "ACTIVE" },
        ] }));
      }
      if (url === "/api/sites/site-1/observation-work-orders") {
        return Promise.resolve(response({ workOrders: [
          { workOrderId: "current", name: "현재 작업", cycleNumber: 1 },
          { workOrderId: "other", name: "기준 작업", cycleNumber: 2 },
        ] }));
      }
      if (url === "/api/observation-work-orders/current/external-reconstruction-submissions" && !init?.method) {
        return Promise.resolve(response({ submissions: [current, sameWorkOrderBaseline] }));
      }
      if (url === "/api/observation-work-orders/other/external-reconstruction-submissions" && !init?.method) {
        return Promise.resolve(response({ submissions: [otherWorkOrderBaseline] }));
      }
      if (url.endsWith("/inspection")) return Promise.resolve(sealedInspection());
      if (url.endsWith("/use-decisions/single")) {
        return Promise.resolve(response({ decision: {
          decisionId: `external-use-decision-${"d".repeat(32)}`, decisionDigest: digest("d"),
          subject: { organizationId: "org-1", siteId: "site-1", workOrderId: "current", submissionId: "sub-current-1", revision: 1, submissionDigest: digest("c"), manifestDigest: digest("d") },
          subjectDigest: digest("e"),
          use: "DISPLAY", verdict: "ELIGIBLE", reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z",
        } }));
      }
      if (url.endsWith("/use-decisions/pair")) {
        pairCalls += 1;
        const pairVerdict = pairCalls <= 2 ? "ELIGIBLE" : "WITHDRAWN";
        return Promise.resolve(response({ decision: {
          decisionId, decisionDigest: digest(pairCalls === 1 ? "a" : "b"),
          baselineSubject: { organizationId: "org-1", siteId: "site-1", workOrderId: "current", submissionId: "sub-baseline-x", revision: 2, submissionDigest: digest("c"), manifestDigest: digest("d") },
          baselineSubjectDigest: digest("e"),
          currentSubject: { organizationId: "org-1", siteId: "site-1", workOrderId: "current", submissionId: "sub-current-1", revision: 1, submissionDigest: digest("c"), manifestDigest: digest("d") },
          currentSubjectDigest: digest("f"),
          use: "RELATIVE_VOLUME", zone: { zoneId: "area-1", revision: 3, definitionDigest: digest("2"), observedCrsDigest: digest("3"), observedVerticalReferenceDigest: digest("4") },
          verdict: pairVerdict, reasons: [], remediations: [], decidedAt: "2026-09-09T00:00:00Z",
        } }));
      }
      if (url === "/api/observation-work-orders/current/relative-volume-requests" && !init?.method) {
        return Promise.resolve(response({ items: [] }));
      }
      if (url === "/api/observation-work-orders/current/relative-volume-requests" && init?.method === "POST") {
        const headers = (init.headers as Record<string, string>) ?? {};
        posts.push({ key: headers["idempotency-key"], body: JSON.parse(String(init?.body)) });
        if (posts.length === 1) return Promise.resolve({ ok: false, status: 503, json: async () => ({ code: "STORE_UNAVAILABLE" }) });
        return Promise.resolve(response({
          verdict: "ISSUED",
          request: { requestRef: `external-relative-volume-${"e".repeat(32)}`, status: "QUEUED", reportRef: null },
          detail: null,
        }));
      }
      if (url.includes("/single-volume-requests")) return Promise.resolve(response({ items: [] }));
      if (url.includes("/observation-work-orders") && !init?.method) return Promise.resolve(response({ workOrders: [] }));
      throw new Error(`unexpected fetch ${url}`);
    });

    const errors: string[] = [];
    const onError = (event: ErrorEvent) => { errors.push(String(event.error ?? event.message)); };
    window.addEventListener("error", onError);
    try {
      render(<ExternalReconstructionPanel workOrderId="current" siteId="site-1" expectedEpochId="epoch-1" canWrite permissions={["SITES_WRITE"]} accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }} />);
      fireEvent.click(await screen.findByRole("button", { name: /current\.tif/ }));
      await waitFor(() => expect(screen.getByLabelText("비교할 이전 등록 버전").querySelectorAll("option").length).toBeGreaterThan(1));
      fireEvent.change(screen.getByLabelText("비교할 이전 등록 버전"), {
        target: { value: `current:${sameWorkOrderBaseline.submissionRef}:2` },
      });
      fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
      fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
      fireEvent.click(await screen.findByRole("button", { name: "상대 물량 비교 요청" }));
      expect(await screen.findByText(/요청 처리를 지금 시작할 수 없습니다. 같은 선택으로 다시 시도합니다/)).toBeTruthy();
      expect(posts).toHaveLength(1);
      const firstKey = posts[0].key;

      fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-2" } });
      expect(await screen.findByText(/이전 상대 물량 비교 요청의 결과를 확인하지 못했습니다/)).toBeTruthy();
      fireEvent.change(screen.getByLabelText("변화 분석 구역"), { target: { value: "area-1" } });
      await waitFor(() => expect(screen.queryByText(/이전 상대 물량 비교 요청의 결과를 확인하지 못했습니다/)).toBeNull());

      // The server returns the same id with a different digest. The old
      // uncertain attempt must not be silently replayed for that new binding.
      fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
      fireEvent.click(await screen.findByRole("button", { name: "새 확인 요청 계속" }));
      await waitFor(() => expect(pairCalls).toBe(2));
      fireEvent.click(await screen.findByRole("button", { name: "상대 물량 비교 요청" }));
      expect(await screen.findByText(/이전 요청의 결과를 확인하지 못했습니다. 새로 요청하면 다른 요청 기록이 생길 수 있습니다/)).toBeTruthy();
      expect(posts).toHaveLength(1);
      fireEvent.click(screen.getByRole("button", { name: "새 요청 계속" }));
      await waitFor(() => expect(posts).toHaveLength(2));
      expect(posts[1].key).not.toBe(firstKey);
      expect(posts[1].body).toEqual({ decisionRef: decisionId });
      expect(await screen.findByText("외부 상대 물량 비교를 요청했습니다.")).toBeTruthy();

      // A later unusable verdict on the same id cannot leave issuance open.
      fireEvent.click(screen.getByRole("button", { name: "변화 분석 다시 확인" }));
      fireEvent.click(await screen.findByRole("button", { name: "새 확인 요청 계속" }));
      await waitFor(() => expect(pairCalls).toBe(3));
      expect(await screen.findByText("현재 선택에서 상대 물량 비교를 요청하세요.")).toBeTruthy();
      expect(screen.queryByRole("button", { name: "상대 물량 비교 요청" })).toBeNull();
      expect(posts).toHaveLength(2);
      expect(errors.filter((message) => message.includes("Maximum update depth"))).toHaveLength(0);
    } finally {
      window.removeEventListener("error", onError);
    }
  }, 30000);
});
