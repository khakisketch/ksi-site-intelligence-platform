/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExternalReconstructionPanel } from "@/app/field/ExternalReconstructionPanel";
import { NotGeoTiffError, type GeoTiffRawHeader } from "@/lib/geo/geotiff-header";

const headerMock = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock("@/lib/geo/geotiff-header", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/geo/geotiff-header")>()),
  readGeoTiffHeader: headerMock.read,
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const fetchMock = vi.fn();
class FakeWorker {
  static instances: FakeWorker[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  terminate = vi.fn();
  constructor() { FakeWorker.instances.push(this); }
  postMessage(request: { id: string }) { void request; }
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("Worker", FakeWorker);
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [] }) });
  FakeWorker.instances = [];
  headerMock.read.mockRejectedValue(new NotGeoTiffError());
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("ExternalReconstructionPanel", () => {
  it("aborts an obsolete inspection request and never applies it to a newly selected WorkOrder", async () => {
    let oldInspectionSignal: AbortSignal | undefined;
    let resolveOldInspection: ((value: unknown) => void) | undefined;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("work-1") && url.endsWith("/external-reconstruction-submissions")) {
        return Promise.resolve({ ok: true, json: async () => ({ submissions: [{ submissionRef: `ers-v1-${"a".repeat(64)}`, state: "SEALED", submission: { revision: 1 } }] }) });
      }
      if (url.includes("work-1") && url.endsWith("/inspection")) {
        oldInspectionSignal = init?.signal ?? undefined;
        return new Promise((resolve) => { resolveOldInspection = resolve; });
      }
      return Promise.resolve({ ok: true, json: async () => ({ submissions: [] }) });
    });
    const { rerender } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    await screen.findByText(/검사 상태 확인 중/);
    rerender(<ExternalReconstructionPanel workOrderId="work-2" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText("등록된 외부 산출물이 없습니다.")).toBeTruthy();
    expect(oldInspectionSignal?.aborted).toBe(true);
    resolveOldInspection?.({ ok: true, json: async () => ({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_REPORTED" }, display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-old", receiptDigest: `sha256:${"e".repeat(64)}` } }) });
    await waitFor(() => expect(screen.queryByRole("button", { name: "정제 정사영상 표시" })).toBeNull());
  });

  it("shows registration, inspection, and sanitized-display status separately without displaying numeric analysis", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/external-reconstruction-submissions")) {
        return { ok: true, json: async () => ({ submissions: [
          { submissionRef: `ers-v1-${"a".repeat(64)}`, state: "REGISTERED", submission: { revision: 1 } },
          { submissionRef: `ers-v1-${"b".repeat(64)}`, state: "SEALED", submission: { revision: 1 } },
          { submissionRef: `ers-v1-${"c".repeat(64)}`, state: "SEALED", submission: { revision: 1 } },
        ] }) };
      }
      if (url.includes(`ers-v1-${"a".repeat(64)}`)) return { ok: true, json: async () => ({ registrationState: "REGISTERED", sealState: "UNSEALED", inspection: { state: "INSPECTION_PENDING_SEAL" }, display: { state: "PENDING_INSPECTION", sanitizedDisplayRef: null, receiptDigest: null } }) };
      if (url.includes(`ers-v1-${"b".repeat(64)}`)) return { ok: true, json: async () => ({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_PENDING", phase: null }, display: { state: "PENDING_INSPECTION", sanitizedDisplayRef: null, receiptDigest: null } }) };
      return { ok: true, json: async () => ({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null }, display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-synthetic-display", receiptDigest: `sha256:${"d".repeat(64)}` } }) };
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText(/등록됨 · 파일 봉인 필요/)).toBeTruthy();
    expect(screen.getByText(/파일 검사 준비 중/)).toBeTruthy();
    expect(screen.getByText(/정제 정사영상 표시 가능/)).toBeTruthy();
    expect(screen.queryByText(/RMSE|절토|성토|순토/)).toBeNull();
  });

  it("retains the last verified inspection and safe display while a manual refresh is pending or fails", async () => {
    let inspectionReads = 0;
    let rejectRefresh: ((reason?: unknown) => void) | undefined;
    fetchMock.mockImplementation((url: string) => {
      if (url.endsWith("/external-reconstruction-submissions")) {
        return Promise.resolve({ ok: true, json: async () => ({ submissions: [{ submissionRef: `ers-v1-${"a".repeat(64)}`, state: "SEALED", submission: { revision: 1 } }] }) });
      }
      if (url.endsWith("/inspection")) {
        inspectionReads += 1;
        if (inspectionReads === 1) return Promise.resolve({ ok: true, json: async () => ({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null }, display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-display", receiptDigest: `sha256:${"d".repeat(64)}` } }) });
        return new Promise((_resolve, reject) => { rejectRefresh = reject; });
      }
      return Promise.resolve({ ok: true, json: async () => ({ items: [] }) });
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText(/정제 정사영상 표시 가능/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "검사 상태 새로고침" }));
    expect(await screen.findByText("마지막으로 확인한 검사 상태를 유지한 채 업데이트를 확인하고 있습니다.")).toBeTruthy();
    expect(screen.getByText(/정제 정사영상 표시 가능/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "정제 정사영상 표시" })).toBeTruthy();
    rejectRefresh?.(new Error("offline"));
    expect(await screen.findByText("검사 상태 업데이트를 확인하지 못했습니다. 마지막으로 확인한 상태를 표시합니다. 새로고침으로 다시 시도하세요.")).toBeTruthy();
    expect(screen.getByText(/정제 정사영상 표시 가능/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "정제 정사영상 표시" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "검사 상태 새로고침" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("stops automatic inspection refresh after a failed read while preserving the verified stage", async () => {
    let inspectionReads = 0;
    fetchMock.mockImplementation((url: string) => {
      if (url.endsWith("/external-reconstruction-submissions")) {
        return Promise.resolve({ ok: true, json: async () => ({ submissions: [{ submissionRef: `ers-v1-${"a".repeat(64)}`, state: "SEALED", submission: { revision: 1 } }] }) });
      }
      if (url.endsWith("/inspection")) {
        inspectionReads += 1;
        if (inspectionReads <= 2) return Promise.resolve({ ok: true, json: async () => ({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_RUNNING", phase: "INSPECTION", outcome: null, request: null, report: null }, display: { state: "PENDING_INSPECTION", sanitizedDisplayRef: null, receiptDigest: null } }) });
        return Promise.reject(new Error("offline"));
      }
      return Promise.resolve({ ok: true, json: async () => ({ items: [] }) });
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText(/파일 검사 중/)).toBeTruthy();
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "검사 상태 새로고침" }));
      await act(async () => { await Promise.resolve(); });
      await vi.advanceTimersByTimeAsync(10_000);
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByText(/파일 검사 중/)).toBeTruthy();
      expect(inspectionReads).toBe(3);
      expect(screen.getByText("자동 상태 확인을 멈췄습니다. 마지막으로 확인한 검사 상태를 표시합니다. 새로고침으로 다시 확인하세요.")).toBeTruthy();
      await vi.advanceTimersByTimeAsync(30_000);
      expect(inspectionReads).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes only an active inspection a bounded number of times and stops after unmount", async () => {
    let inspectionReads = 0;
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/external-reconstruction-submissions")) {
        return { ok: true, json: async () => ({ submissions: [{ submissionRef: `ers-v1-${"a".repeat(64)}`, state: "SEALED", submission: { revision: 1 } }] }) };
      }
      if (url.endsWith("/inspection")) {
        inspectionReads += 1;
        return { ok: true, json: async () => ({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_RUNNING", phase: "INSPECTION", outcome: null, request: null, report: null }, display: { state: "PENDING_INSPECTION", sanitizedDisplayRef: null, receiptDigest: null } }) };
      }
      return { ok: true, json: async () => ({ items: [] }) };
    });
    const { unmount } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    await screen.findByText(/파일 검사 중/);
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "검사 상태 새로고침" }));
      await act(async () => { await Promise.resolve(); });
      // React schedules the next timer after each settled GET; advance through
      // both the timer tick and the following render turn for every budget slot.
      for (let attempt = 0; attempt < 12; attempt += 1) await vi.advanceTimersByTimeAsync(5_000);
      expect(inspectionReads).toBe(8);
      unmount();
      await vi.advanceTimersByTimeAsync(30_000);
      expect(inspectionReads).toBe(8);
    } finally {
      vi.useRealTimers();
    }
  });

  it("distinguishes an empty list from a list failure", async () => {
    const { rerender } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    expect(await screen.findByText("등록된 외부 산출물이 없습니다.")).toBeTruthy();
    expect(screen.getByText(/산출물을 등록하면 제출 revision과 검사 상태가 이 목록에 표시됩니다/)).toBeTruthy();
    fetchMock.mockImplementation((url: string) =>
      url.includes("work-2") && url.endsWith("/external-reconstruction-submissions")
        ? Promise.reject(new Error("offline"))
        : Promise.resolve({ ok: true, json: async () => ({ submissions: [], items: [] }) }),
    );
    rerender(<ExternalReconstructionPanel workOrderId="work-2" expectedEpochId="epoch-1" canWrite />);
    expect(await screen.findByText("선언 목록을 불러오지 못했습니다.")).toBeTruthy();
    expect(screen.queryByText("등록된 외부 산출물이 없습니다.")).toBeNull();
  });

  it("keeps a viewer read-only and fails closed when the inspection payload is malformed", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "SEALED", submission: { revision: 1 } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText("조회 전용 계정입니다.")).toBeTruthy();
    expect(screen.queryByLabelText("정사영상 GeoTIFF")).toBeNull();
    expect(screen.queryByRole("button", { name: "산출물 등록하기" })).toBeNull();
    expect(await screen.findByText(/검사 상태를 불러오지 못했습니다\./)).toBeTruthy();
  });

  it("terminates an active hash worker when the panel unmounts", async () => {
    const { unmount } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    const file = new File(["raster"], "ortho.tif", { type: "application/octet-stream" });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [file] } });
    await waitFor(() => expect(FakeWorker.instances).toHaveLength(1));
    unmount();
    expect(FakeWorker.instances[0].terminate).toHaveBeenCalledTimes(1);
  });
  it("cancels only the active client hash", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["raster"], "ortho.tif")] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "파일 확인 취소" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "파일 확인 취소" }));
    expect(FakeWorker.instances[0].terminate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "파일 확인 취소" })).toBeNull();
  });

  it("offers resume only for a registered server revision", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "등록된 선언 재개" }));
    expect(screen.getByDisplayValue("ODM")).toBeTruthy();
    expect(screen.getByText("등록된 파일과 같은 파일을 다시 선택하세요.")).toBeTruthy();
  });

  it("blocks a fresh registration after closure while preserving a registered declaration continuation", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite newIntentAllowed={false} />);

    expect(await screen.findByText(/업무 종료 상태입니다. 새 산출물 등록은 시작할 수 없지만/)).toBeTruthy();
    expect((screen.getByLabelText("정사영상 GeoTIFF") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "등록된 선언 재개" }));
    expect((screen.getByLabelText("정사영상 GeoTIFF") as HTMLInputElement).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: "새 선언으로 전환" })).toBeNull();
  });

  it("keeps a registered resume action inside the desktop mutation boundary while the list remains readable", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    const resumeButton = await screen.findByRole("button", { name: "등록된 선언 재개" });
    expect(resumeButton.closest("div[class*='hidden'][class*='lg:contents']")).not.toBeNull();
    expect(screen.getByText(/ortho\.tif.*검사 상태를 불러오지 못했습니다\./)).toBeTruthy();
  });

  it("keeps a viewer list error and retry action outside the write boundary", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText("선언 목록을 불러오지 못했습니다.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "목록 다시 시도" })).toBeTruthy();
  });

  it("keeps the readable list beside the compact mutation boundary without a duplicate notice", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    expect(await screen.findByText("등록된 외부 산출물이 없습니다.")).toBeTruthy();
    expect(screen.queryByText("노트북에서 계속")).toBeNull();
    expect(screen.getByLabelText("정사영상 GeoTIFF")).toBeTruthy();
  });

  it("requires and sends the explicit Seoul capture interval for an external ingress", async () => {
    const registrations: Record<string, unknown>[] = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions")) {
        registrations.push(JSON.parse(init.body as string));
        return { ok: true, json: async () => ({ submissionRef: "opaque", submission: { revision: 1 } }) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      return { ok: true, json: async () => ({}) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite requiresCaptureInterval />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    expect((screen.getByRole("button", { name: "산출물 등록하기" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("촬영 시작 시각 (한국 표준시)"), { target: { value: "2026-09-06T09:00:00" } });
    fireEvent.change(screen.getByLabelText("촬영 종료 시각 (한국 표준시)"), { target: { value: "2026-09-06T09:10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await waitFor(() => expect(registrations).toHaveLength(1));
    expect(registrations[0]).toMatchObject({
      captureStartedAt: "2026-09-06T00:00:00Z",
      captureEndedAt: "2026-09-06T00:10:00Z",
    });
  });

  it("starts a required capture interval with neutral help, then alerts only after an invalid edit", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite requiresCaptureInterval />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    expect(screen.getByText("이 외부 등록에는 시작과 종료 시각이 필요합니다.")).toBeTruthy();
    expect(screen.queryByText("시작과 종료를 모두 입력하고, 종료가 시작보다 늦은지 확인하세요.")).toBeNull();
    fireEvent.change(screen.getByLabelText("촬영 시작 시각 (한국 표준시)"), { target: { value: "2026-09-06T09:00:00" } });
    expect(screen.getByText("시작과 종료를 모두 입력하고, 종료가 시작보다 늦은지 확인하세요.").getAttribute("role")).toBe("alert");
  });

  it("retries an uncertain registration with the immutable first attempt", async () => {
    const posts: unknown[] = [];
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(init.body as string));
        throw new Error("lost response");
      }
      return { ok: true, json: async () => ({ submissions: [] }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    const { rerender } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await screen.findByText("산출물 등록을 완료하지 못했습니다. 목록을 다시 확인하세요.");
    rerender(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite newIntentAllowed={false} />);
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual(posts[0]);
  });

  it("creates a new identifier only after the operator explicitly starts a new attempt", async () => {
    const posts: Record<string, unknown>[] = [];
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(init.body as string));
        throw new Error("lost response");
      }
      return { ok: true, json: async () => ({ submissions: [] }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await screen.findByText("산출물 등록을 완료하지 못했습니다. 목록을 다시 확인하세요.");
    fireEvent.click(screen.getByRole("button", { name: "새 선언으로 전환" }));
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1].submissionId).not.toBe(posts[0].submissionId);
  });

  it("resumes an exact registered revision without a current epoch", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "등록된 선언 재개" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    expect((screen.getByRole("button", { name: "산출물 등록하기" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("uses a registered reference for an old epoch without a second declaration POST", async () => {
    const registered = { submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    const requests: Array<{ url: string; method?: string }> = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      requests.push({ url, method: init?.method });
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      return { ok: true, json: async () => ({ submissions: [registered] }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "등록된 선언 재개" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    expect(requests.filter((request) => request.method === "POST" && request.url.endsWith("/external-reconstruction-submissions"))).toHaveLength(0);
    expect(requests.some((request) => request.url.endsWith("/upload-grants"))).toBe(true);
  });

  it("aborts a pending direct upload when the operator cancels transmission", async () => {
    let uploadSignal: AbortSignal | undefined;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (init.method === "PUT") {
        uploadSignal = init.signal ?? undefined;
        return new Promise((_resolve, reject) => {
          uploadSignal?.addEventListener("abort", () => reject(new DOMException("cancelled", "AbortError")), { once: true });
        });
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      return { ok: true, json: async () => ({ submissionRef: "opaque", submission: { revision: 1 } }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await waitFor(() => expect(uploadSignal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "등록 중단" }));
    expect(uploadSignal?.aborted).toBe(true);
    expect(await screen.findByText("등록을 중단했습니다.")).toBeTruthy();
  });

});

describe("ExternalReconstructionPanel header auto-recognition (AX-3)", () => {
  const orthoHeader: GeoTiffRawHeader = {
    width: 4000, height: 3000, samplesPerPixel: 4, bitsPerSample: 8, sampleFormat: 1,
    geoKeys: { ProjectedCSTypeGeoKey: 5186 }, software: "Pix4Dmapper 4.8.4", dateTime: "2026:09:15 10:20:30", pixelSize: [0.05, 0.05],
  };
  const dsmHeader: GeoTiffRawHeader = { ...orthoHeader, samplesPerPixel: 1, bitsPerSample: 32, sampleFormat: 3 };

  function registerFlow() {
    const registrations: Record<string, unknown>[] = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions")) {
        registrations.push(JSON.parse(init.body as string));
        return { ok: true, json: async () => ({ submissionRef: "opaque", submission: { revision: 1 } }) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      return { ok: true, json: async () => ({}) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
    return registrations;
  }

  async function chooseOrtho() {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
  }

  it("pre-fills the CRS and empty producer fields from the header and declares the CRS", async () => {
    const registrations = registerFlow();
    headerMock.read.mockResolvedValue(orthoHeader);
    await chooseOrtho();
    expect(((await screen.findByLabelText("정사영상 좌표계 신고")) as HTMLInputElement).value).toBe("EPSG:5186");
    expect((screen.getByLabelText("재구성 소프트웨어 이름") as HTMLInputElement).value).toBe("Pix4Dmapper");
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).value).toBe("4.8.4");
    expect(screen.getByText(/2026-09-15 10:20:30 \(참고: 소프트웨어에 따라 촬영 시각 또는 파일 생성 시각\)/)).toBeTruthy();
    expect((screen.getByLabelText("촬영 시작 시각 (한국 표준시)") as HTMLInputElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await waitFor(() => expect(registrations).toHaveLength(1));
    expect(registrations[0]).toMatchObject({ softwareName: "Pix4Dmapper", softwareVersion: "4.8.4", captureStartedAt: null });
    expect((registrations[0].artifacts as { declaredCrs: unknown }[])[0].declaredCrs).toBe("EPSG:5186");
  });

  it("never overwrites producer text the operator already typed", async () => {
    registerFlow();
    headerMock.read.mockResolvedValue(orthoHeader);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "Metashape" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByLabelText("정사영상 좌표계 신고");
    expect((screen.getByLabelText("재구성 소프트웨어 이름") as HTMLInputElement).value).toBe("Metashape");
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).value).toBe("4.8.4");
  });

  it("warns when a DSM-looking file is placed in the ortho slot without moving it", async () => {
    registerFlow();
    headerMock.read.mockResolvedValue(dsmHeader);
    await chooseOrtho();
    expect(await screen.findByText(/이 파일은 DSM처럼 보입니다/)).toBeTruthy();
    expect(screen.getByText(/정사영상 1 KB 확인 완료/)).toBeTruthy();
  });

  it("warns on an unreadable header and declares no CRS", async () => {
    const registrations = registerFlow();
    await chooseOrtho();
    expect(await screen.findByText(/GeoTIFF 헤더를 읽지 못했습니다/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await waitFor(() => expect(registrations).toHaveLength(1));
    expect((registrations[0].artifacts as { declaredCrs: unknown }[])[0].declaredCrs).toBeNull();
  });

  it("shows header facts but no CRS field when resuming an already registered declaration", async () => {
    const registered = { submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, observationEpochId: "epoch-1", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    fetchMock.mockImplementation(async () => ({ ok: true, json: async () => ({ submissions: [registered] }) }));
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
    headerMock.read.mockResolvedValue(orthoHeader);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "등록된 선언 재개" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/파일 헤더에서 읽은 정사영상 정보입니다/);
    expect(screen.queryByLabelText("정사영상 좌표계 신고")).toBeNull();
    expect(screen.getByText(/이미 등록된 신고를 그대로 사용합니다/)).toBeTruthy();
  });

  it("declares what the operator leaves in the CRS field, trimmed, or nothing when cleared", async () => {
    const registrations = registerFlow();
    headerMock.read.mockResolvedValue(orthoHeader);
    await chooseOrtho();
    fireEvent.change(await screen.findByLabelText("정사영상 좌표계 신고"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록하기" }));
    await waitFor(() => expect(registrations).toHaveLength(1));
    expect((registrations[0].artifacts as { declaredCrs: unknown }[])[0].declaredCrs).toBeNull();
    expect((screen.getByLabelText("정사영상 좌표계 신고") as HTMLInputElement).disabled).toBe(true);
  });
});
