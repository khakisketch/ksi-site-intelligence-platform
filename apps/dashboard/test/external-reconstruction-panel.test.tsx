/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExternalReconstructionPanel } from "@/app/field/ExternalReconstructionPanel";
import { NotGeoTiffError, type GeoTiffRawHeader } from "@/lib/geo/geotiff-header";

const headerMock = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock("@/lib/geo/geotiff-header", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/geo/geotiff-header")>()),
  readGeoTiffHeader: headerMock.read,
}));

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const fetchMock = vi.fn();
class FakeWorker {
  static instances: FakeWorker[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  terminate = vi.fn();
  constructor() { FakeWorker.instances.push(this); }
  postMessage(request: { id: string }) { void request; }
}

// 서버 확인 계정 비교값 — 합성 신원이며 실제 고객·운영자 신원이 아니다.
// BFF 연속성 가드 동작을 검증하는 테스트는 합성 409로 통제 응답임을 밝힌다.
const continuity = { fingerprint: `v1-${"c".repeat(64)}` };
const ECHO_REF = `ers-v1-${"d".repeat(64)}`;

// 합성 성공 echo — 요청 본문을 그대로 돌려받아 Core 화면 모양으로 감싼다.
// 실제 Core/BFF 계약 검증이 아니라 화면의 echo 대조 분기를 통과시키는 최소
// 합성이며, 여기에 없는 필드·상태는 각 테스트가 명시적으로 바꾼다.
type EchoArtifact = { artifactId: string; kind: string; declaredSha256: string; declaredSizeBytes: number; fileName: string; declaredCrs: string | null };
type EchoBody = {
  submissionId: string; expectedEpochId: string; submittedAt: string | null;
  producerKnowledge: unknown; softwareName: unknown; softwareVersion: unknown; sourceNote: unknown;
  captureBasis: unknown; captureStartedAt: unknown; captureEndedAt: unknown; captureDate: unknown;
  originalRetentionLocus: unknown; originalRetentionDetail: unknown;
  upstreamSource: unknown; derivativeExport: unknown;
  artifacts: EchoArtifact[];
};
// 합성 봉인 식별자 — 실제 Core/BFF 계약 검증이 아니라 화면의 echo 대조 분기를
// 통과시키는 최소 합성이다. 제출 digest와 manifest digest가 같은 값을 가리켜야
// 한다는 결속 자체는 실제 계약과 같다.
const TEST_DIGEST = `sha256:${"e".repeat(64)}`;
// 합성 manifest 식별 다이제스트 — 실제 Core canonical 계산이 아니라 화면의
// manifestDigest 표면(문자열·패턴) 대조를 통과시키는 최소 합성이다. 제출
// digest와 다른 값으로 두어 두 결속이 별개 필드임을 드러낸다.
const TEST_MANIFEST_DIGEST = `sha256:${"d".repeat(64)}`;
// manifest 결속 대조용 최소 합성 — 대조하는 결속 필드(계약 리터럴·제출 묶음·
// 버전·epoch·관측 entries)만 실으며, 대조하지 않는 서버 발급 값은 합성 자리표시다.
function manifestFor(body: { submissionId: string; expectedEpochId: string; artifacts: { artifactId: string; kind: string; declaredSha256: string; declaredSizeBytes: number }[] }, submissionDigest: string) {
  return {
    contractVersion: "external-reconstruction-manifest.v1",
    manifestId: "eman-v1-synthetic",
    submissionId: body.submissionId,
    submissionRevision: 1,
    organizationId: "org-synthetic",
    siteId: "site-synthetic",
    observationEpochId: body.expectedEpochId,
    observedAt: "2026-10-28T00:00:00Z",
    observedByService: "processing-synthetic",
    entries: body.artifacts.map((artifact) => ({
      artifactId: artifact.artifactId,
      kind: artifact.kind,
      objectKey: `external-reconstruction/v1/synthetic-${artifact.kind}`,
      observedSha256: artifact.declaredSha256,
      observedSizeBytes: artifact.declaredSizeBytes,
      observedContentType: "application/octet-stream",
    })),
    manifestDigest: TEST_MANIFEST_DIGEST,
    submissionDigest,
  };
}
function echoDeclaration(body: EchoBody, submissionRef: string = ECHO_REF) {
  return {
    submissionRef,
    state: "REGISTERED",
    submission: {
      submissionId: body.submissionId, revision: 1, observationEpochId: body.expectedEpochId,
      submittedAt: body.submittedAt,
      producerDeclaration: {
        producerKnowledge: body.producerKnowledge, softwareName: body.softwareName,
        softwareVersion: body.softwareVersion, sourceNote: body.sourceNote,
      },
      inputDeclaration: {
        captureBasis: body.captureBasis, captureStartedAt: body.captureStartedAt,
        captureEndedAt: body.captureEndedAt, captureDate: body.captureDate,
        originalRetentionLocus: body.originalRetentionLocus, originalRetentionDetail: body.originalRetentionDetail,
        upstreamSource: body.upstreamSource, derivativeExport: body.derivativeExport,
      },
      artifacts: body.artifacts,
      // Core revision 화면은 봉인 전부터 sealed 제출을 싣는다.
      submissionDigest: TEST_DIGEST,
    },
  };
}
function echoSeal(body: EchoBody, submissionRef: string = ECHO_REF) {
  return {
    submissionRef,
    state: "SEALED",
    submission: {
      submissionId: body.submissionId, revision: 1, observationEpochId: body.expectedEpochId,
      submittedAt: body.submittedAt,
      producerDeclaration: {
        producerKnowledge: body.producerKnowledge, softwareName: body.softwareName,
        softwareVersion: body.softwareVersion, sourceNote: body.sourceNote,
      },
      inputDeclaration: {
        captureBasis: body.captureBasis, captureStartedAt: body.captureStartedAt,
        captureEndedAt: body.captureEndedAt, captureDate: body.captureDate,
        originalRetentionLocus: body.originalRetentionLocus, originalRetentionDetail: body.originalRetentionDetail,
        upstreamSource: body.upstreamSource, derivativeExport: body.derivativeExport,
      },
      artifacts: body.artifacts,
      submissionDigest: TEST_DIGEST,
    },
    manifest: manifestFor(body, TEST_DIGEST),
  };
}
// 유지 제출 기록 기반 봉인 echo — retained 제출과 같은 결속으로 감싼다.
// 합성 409/불명 응답 double이 아니며, 성공 경로에서만 쓴다: 제출 digest와
// manifest digest를 같은 합성값으로 묶는다.
function sealedEchoFor(registered: { submissionRef: string; submission: Record<string, unknown> }) {
  const submission = registered.submission;
  const artifacts = ((submission as { artifacts?: unknown }).artifacts as EchoArtifact[] | undefined) ?? [];
  const normalizedArtifacts = artifacts.map((artifact) => ({
    artifactId: (artifact as Record<string, unknown>).artifactId,
    kind: (artifact as Record<string, unknown>).kind,
    declaredSha256: (artifact as Record<string, unknown>).declaredSha256,
    declaredSizeBytes: (artifact as Record<string, unknown>).declaredSizeBytes,
    fileName: (artifact as Record<string, unknown>).fileName,
    declaredCrs: typeof (artifact as Record<string, unknown>).declaredCrs === "string"
      ? (artifact as Record<string, unknown>).declaredCrs as string
      : null,
  })) as EchoArtifact[];
  return {
    submissionRef: registered.submissionRef,
    state: "SEALED",
    submission: {
      submissionId: (submission as { submissionId?: unknown }).submissionId,
      revision: (submission as { revision?: unknown }).revision,
      observationEpochId: (submission as { observationEpochId?: unknown }).observationEpochId,
      submittedAt: (submission as { submittedAt?: unknown }).submittedAt ?? null,
      producerDeclaration: (submission as { producerDeclaration?: unknown }).producerDeclaration ?? null,
      inputDeclaration: (submission as { inputDeclaration?: unknown }).inputDeclaration ?? null,
      artifacts: normalizedArtifacts,
      submissionDigest: TEST_DIGEST,
    },
    manifest: manifestFor(
      {
        submissionId: (submission as { submissionId?: unknown }).submissionId as string,
        expectedEpochId: submission.observationEpochId as string,
        artifacts: normalizedArtifacts,
      } as EchoBody,
      TEST_DIGEST,
    ),
  };
}
const BOTH_GRANTS = { grants: [
  { artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} },
  { artifactId: "dsm", uploadUrl: "https://upload.test/dsm", requiredHeaders: {} },
] };
// 단일 슬롯 동결의 계약-정확 grant 응답 — Core는 저장 bindings와 1:1로 grant를
// 만들므로 결속된 산출물 집합과 정확히 같아야 한다.
const ORTHO_GRANT = { grants: [
  { artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} },
] };

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("Worker", FakeWorker);
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [] }) });
  FakeWorker.instances = [];
  headerMock.read.mockRejectedValue(new NotGeoTiffError());
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("ExternalReconstructionPanel", () => {
  it("keeps V1 secondary without unmounting its capabilities and reveals both retained deep links", async () => {
    const { unmount } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    const legacy = screen.getByText("이전 비교 흐름(V1) · 검사점·물량·재관측").closest("details") as HTMLDetailsElement;
    expect(legacy.open).toBe(false);
    expect(legacy.querySelector("#external-volume")).not.toBeNull();
    for (const hash of ["#external-volume", "#external-result"]) {
      legacy.open = false;
      act(() => { window.history.replaceState(null, "", hash); window.dispatchEvent(new HashChangeEvent("hashchange")); });
      expect(legacy.open).toBe(true);
    }
    unmount();
    // Initial fragment navigation must reveal V1 too (not just an in-page jump).
    render(<ExternalReconstructionPanel workOrderId="work-2" expectedEpochId="epoch-2" canWrite={false} />);
    expect(screen.getByText("이전 비교 흐름(V1) · 검사점·물량·재관측").closest("details")?.open).toBe(true);
    window.history.replaceState(null, "", window.location.pathname);
  });

  it("gives a viewer read guidance rather than a new-registration disclosure", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    expect(screen.getByText("조회 전용 계정입니다. 등록 자료와 검사 상태를 확인할 수 있습니다.")).toBeTruthy();
    expect(screen.queryByText("새 산출물 등록")).toBeNull();
    expect(screen.queryByRole("button", { name: "자료 등록 마치기" })).toBeNull();
  });

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
    expect(await screen.findByText("아직 등록된 관측 자료가 없습니다.")).toBeTruthy();
    expect(oldInspectionSignal?.aborted).toBe(true);
    resolveOldInspection?.({ ok: true, json: async () => ({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_REPORTED" }, display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-old", receiptDigest: `sha256:${"e".repeat(64)}` } }) });
    await waitFor(() => expect(screen.queryByRole("button", { name: "표시용 정사영상 열기" })).toBeNull());
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
    expect(await screen.findByText(/자료 등록됨 · 파일 제출 마무리 필요/)).toBeTruthy();
    expect(screen.getByText(/파일 검사 준비 중/)).toBeTruthy();
    expect(screen.getByText(/표시용 정사영상 열람 가능/)).toBeTruthy();
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
    expect(await screen.findByText(/표시용 정사영상 열람 가능/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "검사 상태 새로고침" }));
    expect(await screen.findByText("마지막으로 확인한 검사 상태를 유지한 채 업데이트를 확인하고 있습니다.")).toBeTruthy();
    expect(screen.getByText(/표시용 정사영상 열람 가능/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "표시용 정사영상 열기" })).toBeTruthy();
    rejectRefresh?.(new Error("offline"));
    expect(await screen.findByText("검사 상태 업데이트를 확인하지 못했습니다. 마지막으로 확인한 상태를 표시합니다. 새로고침으로 다시 시도하세요.")).toBeTruthy();
    expect(screen.getByText(/표시용 정사영상 열람 가능/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "표시용 정사영상 열기" })).toBeTruthy();
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
    const { rerender } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    expect(await screen.findByText("아직 등록된 관측 자료가 없습니다.")).toBeTruthy();
    expect(screen.getByText(/자료를 등록하면 파일 제출과 검사 상태를 이곳에서 확인할 수 있습니다/)).toBeTruthy();
    fetchMock.mockImplementation((url: string) =>
      url.includes("work-2") && url.endsWith("/external-reconstruction-submissions")
        ? Promise.reject(new Error("offline"))
        : Promise.resolve({ ok: true, json: async () => ({ submissions: [], items: [] }) }),
    );
    rerender(<ExternalReconstructionPanel workOrderId="work-2" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    expect(await screen.findByText("등록 목록을 불러오지 못했습니다.")).toBeTruthy();
    expect(screen.queryByText("아직 등록된 관측 자료가 없습니다.")).toBeNull();
  });

  it("keeps a viewer read-only and fails closed when the inspection payload is malformed", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "SEALED", submission: { revision: 1 } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText("조회 전용 계정입니다. 등록 자료와 검사 상태를 확인할 수 있습니다.")).toBeTruthy();
    expect(screen.queryByLabelText("정사영상 GeoTIFF")).toBeNull();
    expect(screen.queryByRole("button", { name: "자료 등록 마치기" })).toBeNull();
    expect(await screen.findByText(/검사 상태를 불러오지 못했습니다\./)).toBeTruthy();
  });

  it("terminates an active hash worker when the panel unmounts", async () => {
    const { unmount } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    const file = new File(["raster"], "ortho.tif", { type: "application/octet-stream" });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [file] } });
    await waitFor(() => expect(FakeWorker.instances).toHaveLength(1));
    unmount();
    expect(FakeWorker.instances[0].terminate).toHaveBeenCalledTimes(1);
  });
  it("cancels only the active client hash", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["raster"], "ortho.tif")] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "파일 확인 취소" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "파일 확인 취소" }));
    expect(FakeWorker.instances[0].terminate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "파일 확인 취소" })).toBeNull();
  });

  it("offers resume only for a registered server revision", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    expect(screen.getByText("저장된 신고 · 재구성 소프트웨어: ODM 1")).toBeTruthy();
    expect(screen.queryByLabelText("재구성 소프트웨어 이름")).toBeNull();
    expect(screen.getByText("등록된 파일과 같은 파일을 다시 선택하세요.")).toBeTruthy();
  });

  it("blocks a fresh registration after closure while preserving a registered declaration continuation", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite newIntentAllowed={false} accountIdentity={continuity} />);

    expect(await screen.findByText(/업무 종료 상태입니다. 새 산출물 등록은 시작할 수 없지만/)).toBeTruthy();
    expect((screen.getByLabelText("정사영상 GeoTIFF") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "등록 이어하기" }));
    expect((screen.getByLabelText("정사영상 GeoTIFF") as HTMLInputElement).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: "새로 등록하기" })).toBeNull();
  });

  it("keeps a registered resume action inside the desktop mutation boundary while the list remains readable", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    const resumeButton = await screen.findByRole("button", { name: "등록 이어하기" });
    expect(resumeButton.closest("div[class*='hidden'][class*='lg:contents']")).not.toBeNull();
    // 원문은 폐쇄된 파일 정보에 보존하고, 행의 주 표시는 종류·등록 버전으로 둔다.
    const metadata = screen.getByText("파일 정보 · 처리 상세").closest("details");
    expect(metadata?.open).toBe(false);
    expect(metadata?.textContent).toContain("ortho.tif");
    expect(metadata?.textContent).toContain("재구성 소프트웨어: ODM 1");
    expect(metadata?.parentElement?.querySelector("p")?.textContent).not.toContain("ortho.tif");
    expect(screen.getByText(/검사 상태를 불러오지 못했습니다\./)).toBeTruthy();
  });

  it("keeps a viewer list error and retry action outside the write boundary", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect(await screen.findByText("등록 목록을 불러오지 못했습니다.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "목록 다시 시도" })).toBeTruthy();
  });

  it("keeps the readable list beside the compact mutation boundary without a duplicate notice", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    expect(await screen.findByText("아직 등록된 관측 자료가 없습니다.")).toBeTruthy();
    expect(screen.queryByText("노트북에서 계속")).toBeNull();
    expect(screen.getByLabelText("정사영상 GeoTIFF")).toBeTruthy();
  });

  it("requires and sends the explicit Seoul capture interval for an external ingress", async () => {
    const registrations: Record<string, unknown>[] = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        registrations.push(JSON.parse(init.body as string));
        return { ok: true, json: async () => echoDeclaration(JSON.parse(init.body as string) as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      return { ok: true, json: async () => ({}) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite requiresCaptureInterval accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("촬영 시작 시각 (한국 표준시)"), { target: { value: "2026-09-06T09:00:00" } });
    fireEvent.change(screen.getByLabelText("촬영 종료 시각 (한국 표준시)"), { target: { value: "2026-09-06T09:10:00" } });
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "원본 보관 위치" })).getByRole("radio", { name: "고객 작업 장비에 있음" }));
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(registrations).toHaveLength(1));
    expect(registrations[0]).toMatchObject({
      captureBasis: "EXACT_INTERVAL",
      captureStartedAt: "2026-09-06T00:00:00Z",
      captureEndedAt: "2026-09-06T00:10:00Z",
      captureDate: null,
      producerKnowledge: "DECLARED",
      originalRetentionLocus: "customer_workstation",
    });
  });

  it("starts a required capture interval with neutral help, then alerts only after an invalid edit", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite requiresCaptureInterval accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    expect(screen.getByText("외부 관측 등록에는 촬영 구간 확인이 권장됩니다. 미상인 경우 그대로 등록되며, 이후 분석·비교 가능 여부는 별도로 확인합니다.")).toBeTruthy();
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

    const { rerender } = render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("응답을 확인하지 못했습니다. 같은 시도는 같은 식별자로 다시 확인할 수 있으니 목록에서 실제 상태를 먼저 확인하세요.");
    rerender(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite newIntentAllowed={false} accountIdentity={continuity} />);
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual(posts[0]);
    expect(router.refresh).not.toHaveBeenCalled();
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

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("응답을 확인하지 못했습니다. 같은 시도는 같은 식별자로 다시 확인할 수 있으니 목록에서 실제 상태를 먼저 확인하세요.");
    fireEvent.click(screen.getByRole("button", { name: "새로 등록하기" }));
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1].submissionId).not.toBe(posts[0].submissionId);
  });

  it.each([
    ["401", "세션이 만료되어 산출물 등록을 시작하지 못했습니다"],
    ["403", "산출물 등록 권한이 없어 시작하지 못했습니다"],
    ["404", "작업 범위를 확인하지 못해 산출물 등록을 시작하지 못했습니다"],
  ] as const)("releases the frozen declaration with actionable recovery on definitive %s rejection", async (status, message) => {
    const posts: unknown[] = [];
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(init.body as string));
        return { ok: false, status: Number(status), json: async () => ({}) };
      }
      return { ok: true, json: async () => ({ submissions: [] }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(new RegExp(message))).toBeTruthy();
    // 확정 거부는 같은 식별자로 만든 제출이 없으므로 동결을 풀고 폼을 돌려준다.
    expect(screen.queryByRole("button", { name: "새로 등록하기" })).toBeNull();
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(false);
    // 수정 없이 다시 제출하면 같은 신고가 새 동결로 나간다.
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual(posts[0]);
  });

  it("preserves the frozen declaration when a same-key retry is denied", async () => {
    const posts: unknown[] = [];
    let attempts = 0;
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        attempts += 1;
        posts.push(JSON.parse(init.body as string));
        if (attempts === 1) throw new Error("lost response");
        return { ok: false, status: 403, json: async () => ({}) };
      }
      return { ok: true, json: async () => ({ submissions: [] }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("응답을 확인하지 못했습니다. 같은 시도는 같은 식별자로 다시 확인할 수 있으니 목록에서 실제 상태를 먼저 확인하세요.");
    // 모호한 첫 시도 뒤 같은 키 재시도가 거부돼도 원래 동결을 버리지 않는다.
    // 동결 신호: 입력 잠금 + 명시적 새 등록 단추.
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual(posts[0]);
    expect(await screen.findByText("응답을 확인하지 못했습니다. 같은 시도는 같은 식별자로 다시 확인할 수 있으니 목록에서 실제 상태를 먼저 확인하세요.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
  });

  it("retries the submission list without a destructive route refresh and keeps the draft", async () => {
    let listReads = 0;
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/external-reconstruction-submissions")) {
        listReads += 1;
        if (listReads === 1) throw new Error("offline");
        return { ok: true, json: async () => ({ submissions: [] }) };
      }
      return { ok: true, json: async () => ({ submissions: [], items: [] }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    expect(await screen.findByText("등록 목록을 불러오지 못했습니다.")).toBeTruthy();
    // 목록 실패와 무관하게 입력한 초안은 그대로 둔다.
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "목록 다시 시도" }));
    expect(await screen.findByText("아직 등록된 관측 자료가 없습니다.")).toBeTruthy();
    // 목록 복구가 자동 route refresh를 일으키지 않는다 — refresh는 영향받지
    // 않은 상태만 유지하므로 서버 실패 시 패널이 통째로 사라질 수 있다.
    // 초안은 그대로 둔다.
    expect(router.refresh).not.toHaveBeenCalled();
    expect(screen.getByText(/정사영상 1 KB 확인 완료/)).toBeTruthy();
    expect((screen.getByLabelText("재구성 소프트웨어 이름") as HTMLInputElement).value).toBe("ODM");
  });

  it("resumes an exact registered revision without a current epoch", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("resumes accepted date-only bytes without revalidating or resubmitting a new exact-time declaration", async () => {
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: {
      contractVersion: "external-reconstruction-submission.v3", revision: 1, submissionId: "resume-date-only-1", observationEpochId: "epoch-1",
      producerDeclaration: { producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null },
      inputDeclaration: { captureBasis: "DATE_ONLY", captureDate: "2021-08-17", captureStartedAt: null, captureEndedAt: null },
      artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }],
    } };
    const posts: string[] = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (init.method === "POST") posts.push(url);
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      if (url.endsWith("/seal")) {
        return { ok: true, json: async () => sealedEchoFor(registered) };
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite requiresCaptureInterval accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    expect(screen.getByText(/같은 파일의 전송만 재개/)).toBeTruthy();
    expect(screen.queryByRole("radiogroup", { name: "촬영 시점 확인 방식" })).toBeNull();
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    expect(posts.some((url) => url.endsWith("/upload-grants"))).toBe(true);
    expect(posts.some((url) => url.endsWith("/seal"))).toBe(true);
    expect(posts.some((url) => /external-reconstruction-submissions(?:-v[23])?$/.test(url))).toBe(false);
  });

  it("uses a registered reference for an old epoch without a second declaration POST", async () => {
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: { revision: 1, submissionId: "resume-old-epoch-1", observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, inputDeclaration: { captureBasis: "UNKNOWN", captureStartedAt: null, captureEndedAt: null, captureDate: null }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    const requests: Array<{ url: string; method?: string }> = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      requests.push({ url, method: init?.method });
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      if (url.endsWith("/seal")) {
        return { ok: true, json: async () => sealedEchoFor(registered) };
      }
      return { ok: true, json: async () => ({ submissions: [registered] }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    const listReads = () => fetchMock.mock.calls.filter(([url, init]) => !(init as RequestInit | undefined)?.method && (url as string).endsWith("/external-reconstruction-submissions")).length;
    const readsBefore = listReads();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    expect(requests.filter((request) => request.method === "POST" && request.url.endsWith("/external-reconstruction-submissions"))).toHaveLength(0);
    expect(requests.some((request) => request.url.endsWith("/upload-grants"))).toBe(true);
    // 목록은 다시 읽되 자동 route refresh는 하지 않는다 — 상단 배너는
    // 별도 이동·새로고침 때 갱신되며, 그때 미제출 입력·동결 시도는 사라질 수 있다.
    await waitFor(() => expect(listReads()).toBeGreaterThan(readsBefore));
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("keeps the registration form open when nothing is retained", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    const disclosure = screen.getByText("새 산출물 등록").closest("details");
    expect(disclosure?.open).toBe(true);
    expect(screen.getByLabelText("정사영상 GeoTIFF")).toBeTruthy();
  });

  it("puts the new-submission form behind a disclosure when revisions are retained", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "SEALED", submission: { revision: 1 } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    // 유지된 revision 행이 폼보다 먼저 보인다.
    expect(await within(document.getElementById("external-submissions") as HTMLElement).findByText(/산출물 · 등록 버전 1/)).toBeTruthy();
    const disclosure = screen.getByText("새 산출물 등록").closest("details");
    expect(disclosure?.open).toBe(false);
    // 폼은 DOM에 그대로 있어 상태·재시도 맥락을 잃지 않는다.
    expect(screen.getByLabelText("정사영상 GeoTIFF")).toBeTruthy();
    fireEvent.click(screen.getByText("새 산출물 등록"));
    expect((disclosure as HTMLDetailsElement).open).toBe(true);
  });

  it("never hides a resumed attempt behind the disclosure", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    // 재개한 시도는 compactness보다 우선해 항상 보인다.
    expect(screen.getByText("새 산출물 등록").closest("details")?.open).toBe(true);
    expect(screen.getByText("등록된 파일과 같은 파일을 다시 선택하세요.")).toBeTruthy();
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
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        return { ok: true, json: async () => echoDeclaration(JSON.parse(init.body as string) as EchoBody) };
      }
      return { ok: true, json: async () => ({ submissionRef: "opaque", submission: { revision: 1 } }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });

    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(uploadSignal).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "등록 중단" }));
    expect(uploadSignal?.aborted).toBe(true);
    expect(await screen.findByText("등록 중단을 요청했습니다. 이미 접수되거나 전송된 내용이 있을 수 있습니다. 목록을 다시 읽어 실제 상태를 확인하세요.")).toBeTruthy();
  });

});

describe("ExternalReconstructionPanel registration order strip", () => {
  function expectNeutralStaticSequence(strip: HTMLElement) {
    const items = within(strip).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    const classes = items.map((item) => (item as HTMLElement).className);
    // All steps share one neutral style: no accent, no current-step marking.
    expect(new Set(classes).size).toBe(1);
    expect(classes[0]).not.toMatch(/accent/);
    expect(strip.querySelector("[aria-current]")).toBeNull();
  }

  it("labels the strip as an ordinary order, never as live progress", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    expectNeutralStaticSequence(screen.getByRole("list", { name: "등록 순서" }));
    expect(screen.queryByRole("list", { name: "자료 등록 흐름" })).toBeNull();
  });

  it("stays neutral while retained revisions are shown", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [{ submissionRef: "opaque", state: "SEALED", submission: { revision: 1 } }] }) });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await within(document.getElementById("external-submissions") as HTMLElement).findByText(/등록 버전 1/);
    expectNeutralStaticSequence(screen.getByRole("list", { name: "등록 순서" }));
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
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        const body = JSON.parse(init.body as string) as EchoBody;
        registrations.push(body);
        declared = body;
        return { ok: true, json: async () => echoDeclaration(body) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        return declared
          ? { ok: true, json: async () => echoSeal(declared as EchoBody) }
          : { ok: true, json: async () => ({}) };
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
    return registrations;
  }

  async function chooseOrtho() {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
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
    fireEvent.click(screen.getByRole("radio", { name: "정확한 촬영 시각" }));
    expect((screen.getByLabelText("촬영 시작 시각 (한국 표준시)") as HTMLInputElement).value).toBe("");
    fireEvent.click(screen.getByRole("radio", { name: "촬영 시점 미상" }));
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(registrations).toHaveLength(1));
    expect(registrations[0]).toMatchObject({ producerKnowledge: "DECLARED", softwareName: "Pix4Dmapper", softwareVersion: "4.8.4", captureBasis: "UNKNOWN", captureStartedAt: null });
    expect((registrations[0].artifacts as { declaredCrs: unknown }[])[0].declaredCrs).toBe("EPSG:5186");
  });

  it("never overwrites producer text the operator already typed", async () => {
    registerFlow();
    headerMock.read.mockResolvedValue(orthoHeader);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
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
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
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
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
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
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(registrations).toHaveLength(1));
    expect((registrations[0].artifacts as { declaredCrs: unknown }[])[0].declaredCrs).toBeNull();
    expect((screen.getByLabelText("정사영상 좌표계 신고") as HTMLInputElement).disabled).toBe(true);
  });
});

describe("ExternalReconstructionPanel basename preflight", () => {
  function hashAs(sha256: string, size = 1) {
    return vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256, size } } as MessageEvent);
    });
  }

  it("rejects a Korean basename before hashing with actionable copy and no POST", async () => {
    const hashSpy = hashAs("a".repeat(64));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "정사영상_동측.tif")] } });
    const issue = await screen.findByText(/정사영상_동측.tif’ 파일은 등록할 수 없습니다/);
    expect(issue.textContent).toContain("영문 외 문자");
    expect(issue.textContent).toContain("원본 파일은 바꾸지 말고");
    expect(hashSpy).not.toHaveBeenCalled();
    expect(screen.queryByText(/확인 완료/)).toBeNull();
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toHaveLength(0);
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("keeps the previous valid choice, then re-enables on valid reselection or clears it", async () => {
    hashAs("a".repeat(64));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "한글.tif")] } });
    await screen.findByText(/이전에 확인한 정사영상 파일\(ortho.tif\)은 그대로 두었습니다/);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho2.tif")] } });
    await waitFor(() => expect(screen.queryByText(/파일은 등록할 수 없습니다/)).toBeNull());
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "또 한글.tif")] } });
    await screen.findByText(/파일은 등록할 수 없습니다/);
    fireEvent.click(screen.getByRole("button", { name: "이전 선택 지우기" }));
    await waitFor(() => expect(screen.queryByText(/파일은 등록할 수 없습니다/)).toBeNull());
    expect(screen.getByText("등록할 파일(정사영상 또는 DSM)을 선택하세요.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not ban a registered-reference resume over the new-declaration name grammar", async () => {
    const registered = { submissionRef: "opaque", state: "REGISTERED", submission: { revision: 1, observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      return { ok: true, json: async () => ({ submissions: [registered] }) };
    });
    hashAs("a".repeat(64));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "한글.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    expect(screen.queryByText(/파일은 등록할 수 없습니다/)).toBeNull();
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("classifies a 422 declaration as payload-rejected and requires an explicit new attempt", async () => {
    const posts: Record<string, unknown>[] = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        const body = JSON.parse(init.body as string) as EchoBody;
        posts.push(body);
        if (posts.length === 1) return { ok: false, status: 422, json: async () => ({ code: "INVALID" }) };
        return { ok: true, json: async () => echoDeclaration(body) };
      }
      return { ok: true, json: async () => ({}) };
    });
    hashAs("a".repeat(64));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText(/같은 내용으로는 다시 시도해도 접수되지 않습니다/);
    expect(posts).toHaveLength(1);
    expect(router.refresh).not.toHaveBeenCalled();
    // 같은 식별자로는 조용히 재시도하지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(screen.getByText(/같은 내용으로는 다시 시도해도 접수되지 않습니다/)).toBeTruthy());
    expect(posts).toHaveLength(1);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    // 명시적인 새 등록만이 새 식별자를 만든다.
    fireEvent.click(screen.getByRole("button", { name: "새로 등록하기" }));
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1].submissionId).not.toBe(posts[0].submissionId);
  });
});

describe("ExternalReconstructionPanel submit safety", () => {
  function queuedFlow() {
    const posts: string[] = [];
    let releaseUpload: (() => void) | undefined;
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        posts.push(url);
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (init.method === "PUT") return new Promise((resolve) => { releaseUpload = () => resolve({ ok: true }); });
      if (url.endsWith("/seal")) {
        return declared
          ? { ok: true, json: async () => echoSeal(declared as EchoBody) }
          : { ok: true, json: async () => ({}) };
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
    return { posts, release: () => releaseUpload?.() };
  }

  it("sends one declaration for a double click while the first attempt is in flight", async () => {
    const { posts, release } = queuedFlow();
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    const submit = screen.getByRole("button", { name: "자료 등록 마치기" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(posts).toHaveLength(1));
    release();
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    expect(posts).toHaveLength(1);
  });

  it("announces a failed submission as an alert and offers cancellation limits up front", async () => {
    queuedFlow();
    // PUT never resolves here; abort path below covers cancellation.
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      throw new Error("offline");
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    const failure = await screen.findByText("응답을 확인하지 못했습니다. 같은 시도는 같은 식별자로 다시 확인할 수 있으니 목록에서 실제 상태를 먼저 확인하세요.");
    expect(failure.getAttribute("role")).toBe("alert");
  });

  it("reloads the list on cancellation so the actual server state is shown", async () => {
    let listReads = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) {
        listReads += 1;
        return { ok: true, json: async () => ({ submissions: [] }) };
      }
      if (init.method === "PUT") return new Promise(() => undefined);
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        return { ok: true, json: async () => echoDeclaration(JSON.parse(init.body as string) as EchoBody) };
      }
      return { ok: true, json: async () => ({ submissionRef: "opaque", submission: { revision: 1 } }) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    const readsBeforeCancel = listReads;
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText(/등록 중단은 이미 접수·전송된 내용을 되돌리지 않습니다/);
    fireEvent.click(screen.getByRole("button", { name: "등록 중단" }));
    await screen.findByText("등록 중단을 요청했습니다. 이미 접수되거나 전송된 내용이 있을 수 있습니다. 목록을 다시 읽어 실제 상태를 확인하세요.");
    await waitFor(() => expect(listReads).toBeGreaterThan(readsBeforeCancel));
  });
});

describe("ExternalReconstructionPanel sealed completion lock", () => {
  function successFlow(posts: { url: string; body?: unknown }[]) {
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        const body = JSON.parse(init.body as string) as EchoBody;
        posts.push({ url, body });
        declared = body;
        return { ok: true, json: async () => echoDeclaration(body) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        return declared
          ? { ok: true, json: async () => echoSeal(declared as EchoBody) }
          : { ok: true, json: async () => ({}) };
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
  }

  async function fillAndChoose() {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
  }

  it("locks submit after acknowledged seal and unlocks only on explicit new attempt", async () => {
    const posts: { url: string; body?: unknown }[] = [];
    successFlow(posts);
    await fillAndChoose();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    const locked = screen.getByRole("button", { name: "파일 제출 완료" }) as HTMLButtonElement;
    expect(locked.disabled).toBe(true);
    // 목록은 다시 읽되 자동 route refresh는 하지 않는다.
    const listReads = () => fetchMock.mock.calls.filter(([url, init]) => !(init as RequestInit | undefined)?.method && (url as string).endsWith("/external-reconstruction-submissions")).length;
    await waitFor(() => expect(listReads()).toBeGreaterThan(1));
    expect(router.refresh).not.toHaveBeenCalled();
    // 두 번째 클릭은 같은 시도로 다시 보내지 않는다.
    fireEvent.click(locked);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(router.refresh).not.toHaveBeenCalled();
    // 명시적인 새 등록만이 잠금을 풀고 새 식별자를 만든다.
    fireEvent.click(screen.getByRole("button", { name: "새로 등록하기" }));
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect((posts[1].body as Record<string, unknown>).submissionId).not.toBe((posts[0].body as Record<string, unknown>).submissionId);
  });

  it("locks the same way after a registered-reference resume seal", async () => {
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: { revision: 1, submissionId: "resume-lock-1", observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, inputDeclaration: { captureBasis: "UNKNOWN", captureStartedAt: null, captureEndedAt: null, captureDate: null }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    const posts: { url: string; body?: unknown }[] = [];
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      posts.push({ url });
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      if (url.endsWith("/seal")) {
        return { ok: true, json: async () => sealedEchoFor(registered) };
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256: "a".repeat(64), size: 1 } } as MessageEvent);
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    expect((screen.getByRole("button", { name: "파일 제출 완료" }) as HTMLButtonElement).disabled).toBe(true);
    expect(posts.filter((request) => request.url.endsWith("/external-reconstruction-submissions"))).toHaveLength(0);
    // 목록은 다시 읽되 자동 route refresh는 하지 않는다.
    const listReads = () => fetchMock.mock.calls.filter(([url, init]) => !(init as RequestInit | undefined)?.method && (url as string).endsWith("/external-reconstruction-submissions")).length;
    await waitFor(() => expect(listReads()).toBeGreaterThan(1));
    expect(router.refresh).not.toHaveBeenCalled();
  });
});

describe("ExternalReconstructionPanel per-slot name issues", () => {
  function hashAs(sha256: string, size = 1) {
    return vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256, size } } as MessageEvent);
    });
  }

  function declarationPosts() {
    return fetchMock.mock.calls.filter(([url, init]) => (init as RequestInit | undefined)?.method === "POST"
      && (url as string).endsWith("/external-reconstruction-submissions-v3"));
  }

  async function fillTwoValidSlots() {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "dsm.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(false);
  }

  it("holds every outstanding slot rejection: second-slot recovery does not enable the first slot", async () => {
    hashAs("a".repeat(64));
    await fillTwoValidSlots();
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "한글ortho.tif")] } });
    await screen.findByText(/한글ortho.tif’ 파일은 등록할 수 없습니다/);
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "한글dsm.tif")] } });
    await screen.findByText(/한글dsm.tif’ 파일은 등록할 수 없습니다/);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    // DSM만 고쳐도 정사영상 거부가 그대로 남으므로 제출은 막힌다.
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "dsm2.tif")] } });
    await waitFor(() => expect(screen.queryByText(/한글dsm.tif’ 파일은 등록할 수 없습니다/)).toBeNull());
    expect(screen.getByText(/한글ortho.tif’ 파일은 등록할 수 없습니다/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(declarationPosts()).toHaveLength(0);
    // 정사영상을 고르면 풀리고, 그때 단 한 번만 보낸다.
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho2.tif")] } });
    await waitFor(() => expect(screen.queryByText(/파일은 등록할 수 없습니다/)).toBeNull());
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(declarationPosts()).toHaveLength(1));
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("clearing the ortho slot keeps the independent DSM choice and its own rejection", async () => {
    hashAs("a".repeat(64));
    await fillTwoValidSlots();
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "한글ortho.tif")] } });
    await screen.findByText(/한글ortho.tif’ 파일은 등록할 수 없습니다/);
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "한글dsm.tif")] } });
    await screen.findByText(/한글dsm.tif’ 파일은 등록할 수 없습니다/);
    const orthoAlert = screen.getByText(/한글ortho.tif’ 파일은 등록할 수 없습니다/).closest('[role="alert"]') as HTMLElement;
    fireEvent.click(within(orthoAlert).getByRole("button", { name: "이전 선택 지우기" }));
    await waitFor(() => expect(screen.queryByText(/한글ortho.tif’ 파일은 등록할 수 없습니다/)).toBeNull());
    // DSM 칸은 그대로 둔다: 확인된 DSM 파일과 그 칸의 거부가 함께 남는다.
    expect(screen.getByText(/한글dsm.tif’ 파일은 등록할 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/DSM 1 KB 확인 완료/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(declarationPosts()).toHaveLength(0);
    expect(router.refresh).not.toHaveBeenCalled();
  });
});

describe("ExternalReconstructionPanel V3 missing-info intake", () => {
  it("only shows inputs for the selected timing precision and keeps calendar dates timezone-free", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    expect((within(screen.getByRole("radiogroup", { name: "원본 보관 위치" })).getByRole("radio", { name: "미상" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByLabelText("촬영 날짜 (YYYY-MM-DD)")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "정확한 촬영 시각" }));
    fireEvent.change(screen.getByLabelText("촬영 시작 시각 (한국 표준시)"), { target: { value: "2026-10-20T09:00:17" } });
    fireEvent.click(screen.getByRole("radio", { name: "촬영 날짜만 확인됨" }));
    expect(screen.queryByLabelText("촬영 시작 시각 (한국 표준시)")).toBeNull();
    expect(screen.queryByLabelText("촬영 종료 시각 (한국 표준시)")).toBeNull();
    expect(screen.queryByText("촬영 시점 (한국 표준시)", { exact: true })).toBeNull();
    fireEvent.change(screen.getByLabelText("촬영 날짜 (YYYY-MM-DD)"), { target: { value: "2021-08-17" } });
    expect(screen.getByText(/2021\. 8\. 17\. · 시각 미상/)).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "촬영 시점 미상" }));
    expect(screen.queryByLabelText("촬영 날짜 (YYYY-MM-DD)")).toBeNull();
    expect(screen.queryByLabelText("촬영 시작 시각 (한국 표준시)")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "정확한 촬영 시각" }));
    // Native datetime-local serialization may normalize fractional zeroes;
    // compare the exact control value, not one particular textual spelling.
    expect((screen.getByLabelText("촬영 시작 시각 (한국 표준시)") as HTMLInputElement).valueAsNumber).toBe(Date.UTC(2026, 9, 20, 9, 0, 17));
  });

  function hashAs(sha256: string, size = 1) {
    return vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256, size } } as MessageEvent);
    });
  }

  function v3SubmitFlow(posts: Record<string, unknown>[]) {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        posts.push(JSON.parse(init.body as string));
        return { ok: true, json: async () => echoDeclaration(JSON.parse(init.body as string) as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "dsm", uploadUrl: "https://upload.test/dsm", requiredHeaders: {} }] }) };
      return { ok: true, json: async () => ({}) };
    });
  }

  it("registers a DSM-only partial/date-only declaration without inventing times or versions", async () => {
    const posts: Record<string, unknown>[] = [];
    v3SubmitFlow(posts);
    hashAs("b".repeat(64), 2);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "surface.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("radio", { name: "이름만 알고 있음" }));
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "DJI Terra" } });
    fireEvent.click(screen.getByRole("radio", { name: "촬영 날짜만 확인됨" }));
    fireEvent.change(screen.getByLabelText("촬영 날짜 (YYYY-MM-DD)"), { target: { value: "2021-05-17" } });
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "원본 보관 위치" })).getByRole("radio", { name: "미상" }));
    fireEvent.change(screen.getByLabelText("원본 보관 위치 상세"), { target: { value: "portal keeps originals" } });
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      producerKnowledge: "PARTIAL",
      softwareName: "DJI Terra",
      softwareVersion: null,
      sourceNote: null,
      captureBasis: "DATE_ONLY",
      captureStartedAt: null,
      captureEndedAt: null,
      captureDate: "2021-05-17",
      originalRetentionLocus: "unknown",
      originalRetentionDetail: "portal keeps originals",
      upstreamSource: null,
      derivativeExport: null,
    });
    expect((posts[0] as { artifacts: unknown[] }).artifacts).toHaveLength(1);
    expect(JSON.stringify(posts[0])).not.toContain("T00:00:00");
  });

  it("carries optional upstream source and derivative export facts without fetching them", async () => {
    const posts: Record<string, unknown>[] = [];
    v3SubmitFlow(posts);
    hashAs("b".repeat(64), 2);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "surface.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    fireEvent.change(screen.getByLabelText("원본 공개 출처 주소"), { target: { value: "https://example.invalid/source/surface.tif" } });
    fireEvent.change(screen.getByLabelText("원본 확인값"), { target: { value: "c".repeat(64) } });
    fireEvent.change(screen.getByLabelText("내보내기 도구 이름"), { target: { value: "TestExport" } });
    fireEvent.change(screen.getByLabelText("내보내기 도구 버전"), { target: { value: "1.2.3" } });
    fireEvent.change(screen.getByLabelText("내보내기 시각 (한국 표준시)"), { target: { value: "2021-05-18T10:00:00" } });
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      producerKnowledge: "DECLARED",
      captureBasis: "UNKNOWN",
      upstreamSource: {
        sourceUri: "https://example.invalid/source/surface.tif",
        sourceSha256: "c".repeat(64),
      },
      derivativeExport: {
        toolName: "TestExport",
        toolVersion: "1.2.3",
        exportedAt: "2021-05-18T01:00:00Z",
      },
    });
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "PUT").every(([url]) => !(url as string).includes("example.invalid"))).toBe(true);
  });

  it("blocks the fabricated literal unknown instead of submitting it", async () => {
    hashAs("b".repeat(64), 2);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "surface.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "unknown" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    expect(await screen.findByText("소프트웨어 이름·버전에 'unknown'이라고 쓰지 마세요. 미상이면 미상을 선택하세요.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toHaveLength(0);
  });

  it("registers an explicit unknown producer and unknown timing as nulls, never a midnight timestamp", async () => {
    const posts: Record<string, unknown>[] = [];
    v3SubmitFlow(posts);
    hashAs("b".repeat(64), 2);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "surface.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "재구성 소프트웨어 확인 방식" })).getByRole("radio", { name: "미상" }));
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      producerKnowledge: "UNKNOWN",
      softwareName: null,
      softwareVersion: null,
      captureBasis: "UNKNOWN",
      captureStartedAt: null,
      captureEndedAt: null,
      captureDate: null,
    });
    expect(posts[0]).toMatchObject({ softwareName: null, softwareVersion: null, originalRetentionLocus: "unknown" });
    expect(JSON.stringify(posts[0])).not.toContain("T00:00:00");
  });

  it("rejects an unsafe upstream reference before HTTP without echoing it", async () => {
    hashAs("b".repeat(64), 2);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "surface.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    fireEvent.change(screen.getByLabelText("원본 공개 출처 주소"), { target: { value: "ftp://example.invalid/source.tif" } });
    const alert = await screen.findByText("공개 출처 주소가 올바르지 않습니다. http(s) 주소를 그대로 입력하세요.");
    expect(alert.textContent).not.toContain("ftp://");
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toHaveLength(0);
    expect(document.body.textContent).not.toContain("ftp://example.invalid");
  });

  it("shows a partial producer with a version hint as unknown until the operator chooses the name-only way", async () => {
    const posts: Record<string, unknown>[] = [];
    v3SubmitFlow(posts);
    hashAs("b".repeat(64), 2);
    headerMock.read.mockResolvedValue({ width: 4000, height: 3000, samplesPerPixel: 4, bitsPerSample: 8, sampleFormat: 1, geoKeys: { ProjectedCSTypeGeoKey: 5186 }, software: "SomeEngine", dateTime: "2026:09:15 10:20:30", pixelSize: [0.05, 0.05] });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "surface.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    expect((screen.getByLabelText("재구성 소프트웨어 이름") as HTMLInputElement).value).toBe("SomeEngine");
    expect(await screen.findByText("재구성 소프트웨어 이름과 버전을 입력하거나, 미상 방식을 선택하세요.")).toBeTruthy();
    expect(posts).toHaveLength(0);
    fireEvent.click(screen.getByRole("radio", { name: "이름만 알고 있음" }));
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ producerKnowledge: "PARTIAL", softwareName: "SomeEngine", softwareVersion: null });
  });

  it("never asks for raw photos: only ortho/DSM slots exist and retention stays a declaration", async () => {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(2);
    expect(screen.getByText(/제출할 GeoTIFF가 아니라 재구성에 사용한 원본 사진·관측 자료의 보관 위치/)).toBeTruthy();
    expect(screen.getByText(/원본 업로드는 요청하지 않습니다/)).toBeTruthy();
    expect(screen.queryByLabelText(/원본 사진/)).toBeNull();
  });

  it("displays a date-only V3 record with the publisher calendar date and 시각 미상, without timezone conversion", async () => {
    const v3record = {
      submissionRef: `ers-v1-${"d".repeat(64)}`,
      state: "SEALED",
      submission: {
        revision: 1,
        contractVersion: "external-reconstruction-submission.v3",
        observationEpochId: "epoch-1",
        producerDeclaration: { producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null, buildIdentifier: null, producerRunIdentifier: null, configurationDigest: null, completedAt: null, sourceNote: null },
        inputDeclaration: {
          rawMediaStoredByKsi: false, originalRetentionLocus: "upstream_source", originalRetentionDetail: "portal keeps originals",
          localInputManifestDigest: null, imageCount: null,
          captureStartedAt: null, captureEndedAt: null, captureDate: "2021-05-17", captureBasis: "DATE_ONLY",
          upstreamSource: { sourceUri: "https://example.invalid/source/surface.tif", sourceSha256: "c".repeat(64), licenceDeclaration: "publisher page states open reuse", retrievalNote: null },
          derivativeExport: { toolName: "TestExport", toolVersion: "1.2.3", settingsDigest: null, exportedAt: null, exportNote: null },
        },
        artifacts: [{ artifactId: "dsm", kind: "dsm", fileName: "surface.tif", declaredSha256: "b".repeat(64), declaredSizeBytes: 2 }],
      },
    };
    fetchMock.mockImplementation(async (url: string) => {
      if (!url.includes("/inspection")) return { ok: true, json: async () => ({ submissions: [v3record] }) };
      return { ok: true, json: async () => ({ registrationState: "SEALED", sealState: "SEALED", inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null }, display: { state: "NOT_REQUIRED", sanitizedDisplayRef: null, receiptDigest: null } }) };
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite={false} />);
    expect((await screen.findAllByText("재구성 소프트웨어: 미상 (등록 시 확인되지 않음)")).length).toBeGreaterThanOrEqual(1);
    expect((await screen.findAllByText(/2021\. 5\. 17\. · 촬영 시각 미상/)).length).toBeGreaterThanOrEqual(1);
    expect(document.body.textContent).not.toMatch(/촬영시각없음/);
    expect(document.body.textContent).not.toMatch(/2021-05-17T/);
    const metadata = screen.getByText("파일 정보 · 처리 상세").closest("details") as HTMLElement;
    expect(metadata.textContent).toContain("원본 보관: 공개 출처(신고)");
    expect(metadata.textContent).toContain("https://example.invalid/source/surface.tif");
    expect(metadata.textContent).toContain("내보내기 도구: TestExport 1.2.3");
  });

  it("resumes a DSM-only registered record by binding match without a second declaration POST", async () => {
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: { revision: 1, submissionId: "resume-dsm-1", observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, inputDeclaration: { captureBasis: "UNKNOWN", captureStartedAt: null, captureEndedAt: null, captureDate: null }, artifacts: [{ artifactId: "dsm", kind: "dsm", fileName: "surface.tif", declaredSha256: "b".repeat(64), declaredSizeBytes: 2 }] } };
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "dsm", uploadUrl: "https://upload.test/dsm", requiredHeaders: {} }] }) };
      if (url.endsWith("/seal")) {
        return { ok: true, json: async () => sealedEchoFor(registered) };
      }
      return { ok: true, json: async () => ({ submissions: [registered] }) };
    });
    hashAs("b".repeat(64), 2);
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "surface.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts.filter(([url]) => (url as string).endsWith("/external-reconstruction-submissions-v3"))).toHaveLength(0);
    expect(posts.filter(([url]) => (url as string).endsWith("/external-reconstruction-submissions"))).toHaveLength(0);
  });
});

describe("ExternalReconstructionPanel continuity and echo verification", () => {
  function hashAs(sha256: string, size = 1) {
    return vi.spyOn(FakeWorker.prototype, "postMessage").mockImplementation(function (this: FakeWorker, request: { id: string }) {
      this.onmessage?.({ data: { id: request.id, sha256, size } } as MessageEvent);
    });
  }

  async function fillNewOrtho() {
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
  }

  function phaseMock(sealPayload: (declared: EchoBody) => unknown) {
    const seen: Record<string, unknown> = {};
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        const body = JSON.parse(init.body as string) as EchoBody;
        seen.declarationHeaders = init.headers;
        seen.declarationBody = body;
        declared = body;
        return { ok: true, json: async () => echoDeclaration(body) };
      }
      if (url.endsWith("/upload-grants")) {
        seen.grantsHeaders = init.headers;
        return { ok: true, json: async () => ORTHO_GRANT };
      }
      if (url.endsWith("/seal")) {
        seen.sealHeaders = init.headers;
        return { ok: true, json: async () => sealPayload(declared as EchoBody) };
      }
      return { ok: true, json: async () => ({}) };
    });
    return seen;
  }

  it("freezes the verified fingerprint and sends it on declaration, grants and seal", async () => {
    hashAs("a".repeat(64));
    const seen = phaseMock((declared) => echoSeal(declared));
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    expect((seen.declarationHeaders as Record<string, string>)["x-ksi-continuity-fingerprint"]).toBe(continuity.fingerprint);
    expect((seen.grantsHeaders as Record<string, string>)["x-ksi-continuity-fingerprint"]).toBe(continuity.fingerprint);
    expect((seen.sealHeaders as Record<string, string>)["x-ksi-continuity-fingerprint"]).toBe(continuity.fingerprint);
    expect((seen.declarationBody as EchoBody).submissionId).toMatch(/^console-/);
    expect(screen.getByRole("button", { name: "파일 제출 완료" })).toBeTruthy();
    // 목록은 다시 읽되 자동 route refresh는 하지 않는다.
    const listReads = () => fetchMock.mock.calls.filter(([url, init]) => !(init as RequestInit | undefined)?.method && (url as string).endsWith("/external-reconstruction-submissions")).length;
    await waitFor(() => expect(listReads()).toBeGreaterThan(1));
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("blocks new writes without a verified identity but keeps reads", async () => {
    hashAs("a".repeat(64));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={null} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    expect((screen.getByRole("button", { name: "자료 등록 마치기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/계정을 확인하지 못해 산출물 등록을 시작할 수 없습니다/)).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toHaveLength(0);
  });

  it("blocks an explicit resume without a verified identity", async () => {
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: { revision: 1, submissionId: "resume-blocked-1", observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ submissions: [registered] }) });
    hashAs("a".repeat(64));
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={null} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    expect(screen.getByText(/계정을 확인하지 못해 등록 이어하기를 시작할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByText(/등록된 파일과 같은 파일을 다시 선택하세요/)).toBeNull();
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toHaveLength(0);
  });

  it.each([
    ["declaration", "external-reconstruction-submissions-v3"],
    ["grants", "upload-grants"],
    ["seal", "/seal"],
  ] as const)("preserves the frozen attempt on an account-continuity 409 at %s (synthetic BFF response)", async (_phase, suffix) => {
    // 합성: BFF 계정 연속성 거부를 흉내낸 통제 응답이며 실제 BFF/Core 계약 검증이 아니다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        if (suffix === "external-reconstruction-submissions-v3") {
          return { ok: false, status: 409, json: async () => ({ code: "ACCOUNT_CONTINUITY_MISMATCH" }) };
        }
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) {
        if (suffix === "upload-grants") {
          return { ok: false, status: 409, json: async () => ({ code: "ACCOUNT_CONTINUITY_MISMATCH" }) };
        }
        return { ok: true, json: async () => ORTHO_GRANT };
      }
      if (url.endsWith("/seal")) {
        if (suffix === "/seal") {
          return { ok: false, status: 409, json: async () => ({ code: "ACCOUNT_CONTINUITY_MISMATCH" }) };
        }
        return { ok: true, json: async () => echoSeal(declared as EchoBody) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/계정이 바뀌어 같은 요청을 다시 보내지 않았습니다/)).toBeTruthy();
    // 원래 시도·파일·키는 그대로 둔다.
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect((screen.getByLabelText("재구성 소프트웨어 버전") as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
  });

  it("keeps the frozen attempt when an uncertain retry is rejected with 422", async () => {
    hashAs("a".repeat(64));
    const posts: unknown[] = [];
    let attempts = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        attempts += 1;
        posts.push(JSON.parse(init.body as string));
        if (attempts === 1) throw new Error("lost response");
        return { ok: false, status: 422, json: async () => ({ code: "INVALID" }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/다시 보낸 요청이 등록 기준에 맞지 않아 접수되지 않았습니다/)).toBeTruthy();
    expect(await screen.findByText(/이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();
    // 되돌림·부재를 단정하지 않고 동결을 유지한다.
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await waitFor(() => expect(posts).toHaveLength(3));
    expect(posts[1]).toEqual(posts[0]);
    expect(posts[2]).toEqual(posts[0]);
  });

  it("does not mark success on a foreign declaration echo", async () => {
    hashAs("a".repeat(64));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        return { ok: true, json: async () => ({ submissionRef: ECHO_REF, state: "REGISTERED", submission: { submissionId: "someone-else", revision: 1, observationEpochId: "epoch-1", artifacts: [{ kind: "ortho", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on an empty declaration echo", async () => {
    hashAs("a".repeat(64));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) return { ok: true, json: async () => ({}) };
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
  });

  it.each(["malformed", "foreign target", "non-sealed"] as const)("does not mark success on a %s seal echo", async (sealCase) => {
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        if (sealCase === "malformed") return { ok: true, json: async () => ({}) };
        if (sealCase === "foreign target") {
          const foreignBody = { submissionId: "foreign-seal", expectedEpochId: "epoch-1", artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1, declaredCrs: null }] };
          return { ok: true, json: async () => ({ submissionRef: `ers-v1-${"e".repeat(64)}`, state: "SEALED", submission: { submissionId: foreignBody.submissionId, revision: 1, observationEpochId: foreignBody.expectedEpochId, artifacts: foreignBody.artifacts }, manifest: manifestFor(foreignBody as EchoBody, TEST_DIGEST) }) };
        }
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a seal echo with a different valid ref", async () => {
    // 신규: 선언 echo ref와 다른 유효 ref의 봉인은 같은 시도가 아니다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        return { ok: true, json: async () => echoSeal(declared as EchoBody, `ers-v1-${"f".repeat(64)}`) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it.each([["extra artifact", "extra"], ["missing artifact", "missing"]] as const)(
    "does not mark success on a seal echo with %s",
    async (_case, variant) => {
      hashAs("a".repeat(64));
      let declared: EchoBody | null = null;
      fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
        if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
        if (url.endsWith("/external-reconstruction-submissions-v3")) {
          declared = JSON.parse(init.body as string) as EchoBody;
          return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
        }
        if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
        if (url.endsWith("/seal")) {
          const body = declared as EchoBody;
          const artifacts = variant === "extra"
            ? [...body.artifacts, { artifactId: "dsm", kind: "dsm", fileName: "surface.tif", declaredSha256: "b".repeat(64), declaredSizeBytes: 2, declaredCrs: null }]
            : [];
          return { ok: true, json: async () => echoSeal({ ...body, artifacts }, ECHO_REF) };
        }
        return { ok: true, json: async () => ({}) };
      });
      await fillNewOrtho();
      fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
      expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
      expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
      expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    },
  );

  it("does not mark success on a SEALED seal echo without a manifest", async () => {
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        return { ok: true, json: async () => ({ submissionRef: ECHO_REF, state: "SEALED", submission: { submissionId: body.submissionId, revision: 1, observationEpochId: body.expectedEpochId, artifacts: body.artifacts }, manifest: null }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
  });

  it("does not mark success on a resume seal echo with a different ref", async () => {
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: { revision: 1, submissionId: "resume-ref-1", observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    hashAs("a".repeat(64));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        // ref만 다르고 결속은 같은 응답 — ref 동등성 대조에서 걸려야 한다.
        return { ok: true, json: async () => ({ ...sealedEchoFor(registered), submissionRef: `ers-v1-${"f".repeat(64)}` }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
  });

  it("recovers a sealed replay of the same frozen declaration without re-uploading (synthetic double)", async () => {
    // 합성: 첫 등록 응답 유실 뒤 같은 선언 replay가 SEALED 기록으로 돌아오는
    // fetch double이며 실제 Core/BFF 계약 검증이 아니다.
    hashAs("a".repeat(64));
    const posts: { url: string; body?: unknown }[] = [];
    let attempts = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        attempts += 1;
        const replayBody = JSON.parse(init.body as string) as EchoBody;
        posts.push({ url, body: replayBody });
        if (attempts === 1) throw new Error("lost response after seal");
        return { ok: true, json: async () => echoSeal(replayBody) };
      }
      if (init.method === "POST") posts.push({ url });
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
    expect((screen.getByRole("button", { name: "파일 제출 완료" }) as HTMLButtonElement).disabled).toBe(true);
    const declarations = posts.filter(({ url }) => url.endsWith("/external-reconstruction-submissions-v3"));
    expect(declarations).toHaveLength(2);
    expect(declarations[1].body).toEqual(declarations[0].body);
    // PUT/grant/seal 추가 재발행 없이 이전 기록 확인으로 복구한다.
    expect(posts.some(({ url }) => url.endsWith("/upload-grants") || url.endsWith("/seal"))).toBe(false);
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "PUT")).toHaveLength(0);
    // 목록은 다시 읽되 자동 route refresh는 하지 않는다.
    const replayListReads = () => fetchMock.mock.calls.filter(([url, init]) => !(init as RequestInit | undefined)?.method && (url as string).endsWith("/external-reconstruction-submissions")).length;
    await waitFor(() => expect(replayListReads()).toBeGreaterThan(1));
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("stays blocked on an account-continuity 409 for a same-key retry (synthetic BFF response)", async () => {
    // 합성: 통제된 BFF 409 응답이며 실제 BFF/Core 계약 검증이 아니다.
    hashAs("a".repeat(64));
    const posts: unknown[] = [];
    let attempts = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        attempts += 1;
        posts.push(JSON.parse(init.body as string));
        if (attempts === 1) throw new Error("lost response");
        return { ok: false, status: 409, json: async () => ({ code: "ACCOUNT_CONTINUITY_MISMATCH" }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/계정이 바뀌어 같은 요청을 다시 보내지 않았습니다/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(posts).toHaveLength(2);
    expect(posts[1]).toEqual(posts[0]);
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("stays blocked on a conflicting retry without claiming success (synthetic BFF response)", async () => {
    // 합성: 같은 식별자에 다른 내용이 이미 있다는 통제된 BFF 409 응답이다.
    hashAs("a".repeat(64));
    let attempts = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        attempts += 1;
        if (attempts === 1) throw new Error("lost response");
        return { ok: false, status: 409, json: async () => ({ code: "CONFLICT" }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a seal echo with a duplicated kind", async () => {
    // 같은 종류 두 건은 길이가 맞아도 집합이 아니므로 거부한다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        const dup = { artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1, declaredCrs: null as string | null };
        return { ok: true, json: async () => ({ ...echoSeal(body), submission: { submissionId: body.submissionId, revision: 1, observationEpochId: body.expectedEpochId, artifacts: [dup, { ...dup }] }, manifest: manifestFor({ ...body, artifacts: [dup, { ...dup }] }, TEST_DIGEST) }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a seal echo with an artifactId mismatch", async () => {
    // echo artifactId가 동결된 것과 다르면 같은 산출물이 아니다 — 키 기준 대조.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        const swapped = [{ artifactId: "dsm", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1, declaredCrs: null as string | null }];
        return { ok: true, json: async () => ({ ...echoSeal(body), submission: { submissionId: body.submissionId, revision: 1, observationEpochId: body.expectedEpochId, artifacts: swapped }, manifest: manifestFor({ ...body, artifacts: swapped }, TEST_DIGEST) }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a seal echo whose manifest binds a different submission", async () => {
    // 제출 묶음은 맞지만 manifest가 다른 제출을 가리키면 확정하지 않는다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        return { ok: true, json: async () => ({ ...echoSeal(body), manifest: manifestFor({ submissionId: "someone-else", expectedEpochId: body.expectedEpochId, artifacts: body.artifacts }, TEST_DIGEST) }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a seal echo with empty manifest entries", async () => {
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        return { ok: true, json: async () => ({ ...echoSeal(body), manifest: { ...manifestFor(body, TEST_DIGEST), entries: [] } }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a REGISTERED declaration echo carrying a manifest", async () => {
    // REGISTERED인데 manifest가 있으면 계약 표면이 어긋난 것이므로 확정하지 않는다.
    hashAs("a".repeat(64));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        const body = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => ({ ...echoDeclaration(body), manifest: manifestFor(body, TEST_DIGEST) }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not recover a sealed replay whose manifest binds a different submission", async () => {
    // 합성: replay 응답의 manifest가 다른 제출을 가리키는 통제 응답이다.
    hashAs("a".repeat(64));
    let attempts = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        attempts += 1;
        const replayBody = JSON.parse(init.body as string) as EchoBody;
        if (attempts === 1) throw new Error("lost response after seal");
        return { ok: true, json: async () => ({ ...echoSeal(replayBody), manifest: manifestFor({ submissionId: "someone-else", expectedEpochId: replayBody.expectedEpochId, artifacts: replayBody.artifacts }, TEST_DIGEST) }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a resume seal echo whose manifest binds a different submission", async () => {
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: { revision: 1, submissionId: "resume-manifest-1", observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    hashAs("a".repeat(64));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        return { ok: true, json: async () => ({ ...sealedEchoFor(registered), manifest: manifestFor({ submissionId: "someone-else", expectedEpochId: "old-epoch", artifacts: registered.submission.artifacts }, TEST_DIGEST) }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a two-slot seal echo missing one kind", async () => {
    // 두 슬롯을 동결했는데 echo가 한 종류만 돌려주면 집합 불일치로 둔다.
    // grant는 결속 집합과 정확히 같아야 통과하므로 두 슬롯분을 둔다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => BOTH_GRANTS };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        const orthoOnly = body.artifacts.filter((artifact) => artifact.kind === "ortho");
        return { ok: true, json: async () => echoSeal({ ...body, artifacts: orthoOnly }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId="epoch-1" canWrite accountIdentity={continuity} />);
    await screen.findByText("아직 등록된 관측 자료가 없습니다.");
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 이름"), { target: { value: "ODM" } });
    fireEvent.change(screen.getByLabelText("재구성 소프트웨어 버전"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "dsm.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("resumes a V1-style custom artifactId by binding the stored identifier", async () => {
    // artifactId===kind는 V3 신규 등록 본문 검증일 뿐 범용 제약이 아니다.
    // 유지된 V1 기록의 사용자 정의 ID와 echo·grant·manifest가 같은 저장
    // 식별자로 결속하면 이어가기가 성공한다. grant 조회는 슬롯 키가 아니라
    // 결속된 저장 artifact_id로 한다.
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: { revision: 1, submissionId: "resume-custom-id-1", observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, inputDeclaration: { captureBasis: "UNKNOWN", captureStartedAt: null, captureEndedAt: null, captureDate: null }, artifacts: [{ artifactId: "ortho-custom-1", kind: "ortho", fileName: "ortho.tif", declaredSha256: "a".repeat(64), declaredSizeBytes: 1 }] } };
    hashAs("a".repeat(64));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "ortho-custom-1", uploadUrl: "https://upload.test/ortho", requiredHeaders: {} }] }) };
      if (url.endsWith("/seal")) {
        return { ok: true, json: async () => sealedEchoFor(registered) };
      }
      return { ok: true, json: async () => ({}) };
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("정사영상 GeoTIFF"), { target: { files: [new File(["x"], "ortho.tif")] } });
    await screen.findByText(/정사영상 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "파일 제출 완료" }) as HTMLButtonElement).disabled).toBe(true);
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("resumes a V2-style custom DSM artifactId by binding the stored identifier", async () => {
    // V2도 artifact_id는 제출 내 유일한 자유 문자열이다. DSM 사용자 정의 ID
    // 기록이 grant·manifest와 같은 저장 식별자로 결속하면 이어가기가 성공한다.
    const registered = { submissionRef: ECHO_REF, state: "REGISTERED", submission: { contractVersion: "external-reconstruction-submission.v2", revision: 1, submissionId: "resume-v2-custom-1", observationEpochId: "old-epoch", producerDeclaration: { softwareName: "ODM", softwareVersion: "1" }, inputDeclaration: { captureBasis: "UNKNOWN", captureStartedAt: null, captureEndedAt: null, captureDate: null }, artifacts: [{ artifactId: "dsm-custom-7", kind: "dsm", fileName: "surface.tif", declaredSha256: "b".repeat(64), declaredSizeBytes: 2 }] } };
    hashAs("b".repeat(64), 2);
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [registered] }) };
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [{ artifactId: "dsm-custom-7", uploadUrl: "https://upload.test/dsm", requiredHeaders: {} }] }) };
      if (url.endsWith("/seal")) {
        return { ok: true, json: async () => sealedEchoFor(registered) };
      }
      return { ok: true, json: async () => ({}) };
    });
    render(<ExternalReconstructionPanel workOrderId="work-1" expectedEpochId={null} canWrite accountIdentity={continuity} />);
    fireEvent.click(await screen.findByRole("button", { name: "등록 이어하기" }));
    fireEvent.change(screen.getByLabelText("DSM GeoTIFF"), { target: { files: [new File(["x"], "surface.tif")] } });
    await screen.findByText(/DSM 1 KB 확인 완료/);
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "파일 제출 완료" }) as HTMLButtonElement).disabled).toBe(true);
    const posts = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(posts.filter(([url]) => (url as string).endsWith("/external-reconstruction-submissions-v3"))).toHaveLength(0);
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not start an upload when grants carry an artifact outside the frozen set", async () => {
    // Core는 저장 bindings와 1:1로 grant를 만들므로 여분은 계약 표면이
    // 어긋난 것이다. 바인딩되지 않은 grant에 PUT하지 않고 모름으로 둔다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => BOTH_GRANTS };
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "PUT")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not start an upload when grants miss a frozen artifact", async () => {
    // 결속 집합보다 grant가 모자라도 같은 capability를 확정할 수 없으므로
    // 전송하지 않고 모름으로 둔다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ({ grants: [] }) };
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "PUT")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a seal echo whose submission misses its digest", async () => {
    // Core revision 화면은 sealed 제출을 실으므로 submissionDigest 없는
    // SEALED는 계약 표면이 어긋난 것이다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        const sealed = echoSeal(body);
        const sealedSubmission = { ...(sealed.submission as unknown as Record<string, unknown>) };
        delete sealedSubmission.submissionDigest;
        return { ok: true, json: async () => ({ ...sealed, submission: sealedSubmission }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a seal echo whose manifest misses its digest", async () => {
    // Core는 봉인된 manifest에만 manifestDigest를 적는다. 없는 manifest는
    // 계약 표면이 어긋난 것이므로 확정하지 않는다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        return { ok: true, json: async () => ({ ...echoSeal(body), manifest: { ...manifestFor(body, TEST_DIGEST), manifestDigest: null } }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success on a declaration echo whose submission misses its digest", async () => {
    // REGISTERED 응답도 sealed 제출을 실어야 한다. digest 없는 선언 echo는
    // 계약 표면이 어긋난 것이므로 확정하지 않는다.
    hashAs("a".repeat(64));
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        const body = JSON.parse(init.body as string) as EchoBody;
        const declared = echoDeclaration(body);
        const declaredSubmission = { ...(declared.submission as unknown as Record<string, unknown>) };
        delete declaredSubmission.submissionDigest;
        return { ok: true, json: async () => ({ ...declared, submission: declaredSubmission }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success when the producer declaration differs from the frozen attempt", async () => {
    // 제작자 신고(소프트웨어명)가 다르면 같은 시도가 아니다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        return { ok: true, json: async () => ({ ...echoSeal(body), submission: { ...(echoSeal(body).submission as object), producerDeclaration: { producerKnowledge: body.producerKnowledge, softwareName: "다른도구", softwareVersion: body.softwareVersion, sourceNote: body.sourceNote } } }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success when the upstream declaration differs from the frozen attempt", async () => {
    // 원본 공개 출처 신고가 다르면 같은 시도가 아니다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        const sealed = echoSeal(body);
        const sealedInput = sealed.submission.inputDeclaration as unknown as Record<string, unknown>;
        const forgedUpstream = { ...(sealedInput.upstreamSource as Record<string, unknown> | null ?? {}), sourceUri: "https://example.invalid/other.tif" };
        return { ok: true, json: async () => ({ ...sealed, submission: { ...(sealed.submission as object), inputDeclaration: { ...sealedInput, upstreamSource: forgedUpstream } } }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success when the seal manifest digest differs from the submission digest", async () => {
    // manifest 결속이 제출과 어긋나면 확정하지 않는다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        return { ok: true, json: async () => ({ ...echoSeal(body), manifest: { ...manifestFor(body, TEST_DIGEST), submissionDigest: `sha256:${"f".repeat(64)}` } }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success when the seal digests match each other but break the digest shape", async () => {
    // 제출·manifest 양쪽 submissionDigest가 같은 비어 있지 않은 잘못된 문자열이면
    // 동등 검사는 통과하지만 Core 계약(_DIGEST_PATTERN) 표면이 아니므로 확정하지 않는다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        return { ok: true, json: async () => ({ ...echoSeal(body), submission: { ...(echoSeal(body).submission as object), submissionDigest: "not-a-digest" }, manifest: manifestFor(body, "not-a-digest") }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not recover a sealed replay whose digests break the digest shape", async () => {
    // 합성: 첫 등록 응답 유실 뒤 돌아온 SEALED replay의 양쪽 digest가 같은 잘못된
    // 문자열인 통제 응답이다. 동등하지만 계약 표면이 아니므로 복구하지 않는다.
    hashAs("a".repeat(64));
    let attempts = 0;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        attempts += 1;
        const replayBody = JSON.parse(init.body as string) as EchoBody;
        if (attempts === 1) throw new Error("lost response after seal");
        const sealed = echoSeal(replayBody);
        return { ok: true, json: async () => ({ ...sealed, submission: { ...(sealed.submission as object), submissionDigest: "not-a-digest" }, manifest: manifestFor(replayBody, "not-a-digest") }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not mark success when the file name differs from the frozen declaration", async () => {
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) return { ok: true, json: async () => ORTHO_GRANT };
      if (url.endsWith("/seal")) {
        const body = declared as EchoBody;
        const renamed = (body.artifacts as EchoArtifact[]).map((artifact) => ({ ...artifact, fileName: "renamed.tif" }));
        return { ok: true, json: async () => ({ ...echoSeal(body), submission: { ...(echoSeal(body).submission as object), artifacts: renamed }, manifest: manifestFor({ ...body, artifacts: renamed }, TEST_DIGEST) }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("does not start an upload when grants contain a duplicated artifact", async () => {
    // 같은 슬롯 grant가 둘 이상이면 어느 capability로 보낼지 확정할 수 없다.
    hashAs("a".repeat(64));
    let declared: EchoBody | null = null;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (!init?.method) return { ok: true, json: async () => ({ submissions: [] }) };
      if (url.endsWith("/external-reconstruction-submissions-v3")) {
        declared = JSON.parse(init.body as string) as EchoBody;
        return { ok: true, json: async () => echoDeclaration(declared as EchoBody) };
      }
      if (url.endsWith("/upload-grants")) {
        return { ok: true, json: async () => ({ grants: [BOTH_GRANTS.grants[0], BOTH_GRANTS.grants[0]] }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    await fillNewOrtho();
    fireEvent.click(screen.getByRole("button", { name: "자료 등록 마치기" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다\. 같은 시도는 같은 식별자로 다시 확인할 수 있으니/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "파일 제출 완료" })).toBeNull();
    expect(screen.getByRole("button", { name: "새로 등록하기" })).toBeTruthy();
    expect(router.refresh).not.toHaveBeenCalled();
  });
});
