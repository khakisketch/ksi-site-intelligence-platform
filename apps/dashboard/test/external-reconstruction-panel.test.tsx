/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExternalReconstructionPanel } from "@/app/field/ExternalReconstructionPanel";

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
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("ExternalReconstructionPanel", () => {
  it("distinguishes an empty list from a list failure", async () => {
    const { rerender } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    expect(await screen.findByText("등록된 외부 산출물이 없습니다.")).toBeTruthy();
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    rerender(<ExternalReconstructionPanel workOrderId="work-2" expectedEpochId="epoch-1" canWrite />);
    expect(await screen.findByText("선언 목록을 불러오지 못했습니다.")).toBeTruthy();
    expect(screen.queryByText("등록된 외부 산출물이 없습니다.")).toBeNull();
  });

  it("keeps a viewer read-only while preserving the observed-byte state label", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "SEALED", submission: { revision: 1 } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText("조회 전용 계정입니다.")).toBeTruthy();
    expect(screen.queryByLabelText("정사영상 GeoTIFF")).toBeNull();
    expect(screen.queryByRole("button", { name: "선언·업로드·봉인" })).toBeNull();
    expect(screen.getByText(/파일 저장 확인 · 형식·품질 검사 미완료/)).toBeTruthy();
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
    await waitFor(() => expect(screen.getByRole("button", { name: "해시 취소" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "해시 취소" }));
    expect(FakeWorker.instances[0].terminate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "해시 취소" })).toBeNull();
  });

  it("offers resume only for a registered server revision", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "등록된 선언 재개" }));
    expect(screen.getByDisplayValue("ODM")).toBeTruthy();
    expect(screen.getByText("등록된 선언과 같은 파일을 다시 선택하세요.")).toBeTruthy();
  });

  it("keeps a registered resume action inside the desktop mutation boundary while the list remains readable", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    const resumeButton = await screen.findByRole("button", { name: "등록된 선언 재개" });
    expect(resumeButton.closest("div[class*='hidden'][class*='lg:contents']")).not.toBeNull();
    expect(screen.getByText(/ortho\.tif.*등록됨 · 파일 저장 미확인/)).toBeTruthy();
  });

  it("keeps a viewer list error and retry action outside the write boundary", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText("선언 목록을 불러오지 못했습니다.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "목록 다시 시도" })).toBeTruthy();
  });

  it("keeps the readable list beside the compact mutation notice", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    expect(await screen.findByText("등록된 외부 산출물이 없습니다.")).toBeTruthy();
    expect(screen.getByText("노트북에서 계속")).toBeTruthy();
    expect(screen.getByLabelText("정사영상 GeoTIFF")).toBeTruthy();
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

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite />);
    await screen.findByText("등록된 외부 산출물이 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 bytes 해시 완료/);
    fireEvent.click(screen.getByRole("button", { name: "선언·업로드·봉인" }));
    await screen.findByText("선언 또는 바이트 봉인에 실패했습니다. 목록을 다시 확인하세요.");
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "선언·업로드·봉인" }));
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
    await screen.findByText(/정사영상 1 bytes 해시 완료/);
    fireEvent.click(screen.getByRole("button", { name: "선언·업로드·봉인" }));
    await screen.findByText("선언 또는 바이트 봉인에 실패했습니다. 목록을 다시 확인하세요.");
    fireEvent.click(screen.getByRole("button", { name: "새 선언으로 전환" }));
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "선언·업로드·봉인" }));
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
    await screen.findByText(/정사영상 1 bytes 해시 완료/);
    expect((screen.getByRole("button", { name: "선언·업로드·봉인" }) as HTMLButtonElement).disabled).toBe(false);
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
    await screen.findByText(/정사영상 1 bytes 해시 완료/);
    fireEvent.click(screen.getByRole("button", { name: "선언·업로드·봉인" }));
    await screen.findByText("바이트 관측을 Core에 요청했습니다. 파일 형식·품질 또는 측정 적합성은 아직 검증되지 않았습니다.");
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
    await screen.findByText(/정사영상 1 bytes 해시 완료/);
    fireEvent.click(screen.getByRole("button", { name: "선언·업로드·봉인" }));
    await waitFor(() => expect(uploadSignal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "전송 취소" }));
    expect(uploadSignal?.aborted).toBe(true);
    expect(await screen.findByText("전송을 취소했습니다.")).toBeTruthy();
  });

});
