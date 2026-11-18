import { isAccountContinuityMismatch } from "@/lib/account-continuity-mismatch";
import {
  declarationEchoOfRequest,
  isRevisionViewForAttempt,
  isUploadGrantView,
  type Revision,
} from "@/lib/external-submission-echo";
import { putExternalReconstructionFile, type DirectUploadGrant } from "@/lib/external-reconstruction-upload";
import type { ExternalArtifactKind } from "@/lib/external-reconstruction-submission";
import { defaultObservationName } from "@/lib/observation-default-name";
import { buildSimpleUploadBody, type SimpleUploadBody, type SimpleUploadFile } from "@/lib/site-upload-declaration";

/**
 * 현장 화면의 한 번에 올리기: 작업 만들기 → 관측 시점 읽기 → 신고 등록 → 파일 올리기 → 봉인.
 *
 * 이 흐름은 기존 등록 화면의 안전 규칙을 그대로 따른다. 모든 단계의 응답은 이번 시도의 응답인지
 * 대조하고, 응답을 확인하지 못한 단계(5xx·네트워크·대조 불일치)는 같은 키·같은 신고서로 다시 보낸다
 * (Core가 멱등으로 같은 결과를 돌려준다). 서버가 분명히 거부한 단계(4xx)만 확정 실패로 알린다.
 * 한 번 끝난 단계는 다시 하지 않는다.
 */

export type UploadFlowFile = SimpleUploadFile & { file: File };

export type UploadFlowInput = {
  siteId: string;
  workAreaId: string;
  workAreaName: string;
  /** 서버가 계산한 계정 비교값(BFF 비교 보조). */
  continuity: string;
  files: readonly UploadFlowFile[];
  startedLocal: string;
  endedLocal: string;
};

export type UploadFlowStage = "workOrder" | "register" | "upload" | "seal";

export type UploadFlowEvent =
  | { type: "stage"; stage: UploadFlowStage }
  | { type: "progress"; kind: ExternalArtifactKind; transferredBytes: number; totalBytes: number }
  | { type: "fileDone"; kind: ExternalArtifactKind };

export type UploadFlowResult = { workOrderId: string; submissionRef: string; revision: number };

/** `ambiguous`면 Core가 처리했는지 알 수 없으니 같은 요청으로 다시 시도해도 된다. 아니면 서버가 거부했다. */
export class UploadFlowError extends Error {
  readonly stage: UploadFlowStage;
  readonly ambiguous: boolean;
  constructor(stage: UploadFlowStage, ambiguous: boolean, message: string) {
    super(message);
    this.name = "UploadFlowError";
    this.stage = stage;
    this.ambiguous = ambiguous;
  }
}

export type UploadFlowDeps = {
  fetch: typeof fetch;
  put: (grant: DirectUploadGrant, file: File, signal: AbortSignal | undefined, onBytes: (transferred: number) => void) => Promise<void>;
  uuid: () => string;
  now: () => Date;
};

const CONTINUITY_HEADER = "x-ksi-continuity-fingerprint";

const defaultDeps: UploadFlowDeps = {
  fetch: (...args) => fetch(...args),
  put: (grant, file, signal, onBytes) => putExternalReconstructionFile(grant, file, signal, onBytes),
  uuid: () => crypto.randomUUID(),
  now: () => new Date(),
};

const AMBIGUOUS_MESSAGE = "응답을 확인하지 못했습니다. 다시 시도하면 같은 요청으로 이어서 확인합니다.";
const MISMATCH_MESSAGE = "계정이 바뀌어 요청을 보내지 않았습니다. 원래 계정으로 다시 로그인한 뒤 같은 화면에서 다시 시도하세요.";

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function definiteMessage(stage: UploadFlowStage, status: number): string {
  if (status === 401) return "로그인이 만료되었습니다. 다시 로그인한 뒤 올려 주세요.";
  if (status === 403) return "이 현장에 자료를 올릴 권한이 없습니다. 현장 담당자에게 권한을 요청하세요.";
  if (status === 404) return "현장이나 작업구역을 찾지 못했습니다. 화면을 새로 고친 뒤 다시 시도하세요.";
  if (status === 422) return stage === "register"
    ? "올린 내용이 등록 기준에 맞지 않아 접수되지 않았습니다. 파일과 촬영 시각을 확인하세요."
    : "요청이 기준에 맞지 않아 접수되지 않았습니다.";
  if (status === 409) return "이미 닫힌 작업이거나 다른 요청과 충돌했습니다. 화면을 새로 고친 뒤 다시 시도하세요.";
  return AMBIGUOUS_MESSAGE;
}

export class UploadSession {
  private readonly workOrderKey: string;
  private readonly submissionId: string;
  private readonly submittedAt: string;
  private workOrderId: string | null = null;
  private body: SimpleUploadBody | null = null;
  private revision: Revision | null = null;
  private readonly uploaded = new Set<ExternalArtifactKind>();
  private sealed = false;

  constructor(private readonly input: UploadFlowInput, private readonly deps: UploadFlowDeps = defaultDeps) {
    this.workOrderKey = `site-upload-${deps.uuid()}`;
    this.submissionId = `console-${deps.uuid()}`;
    this.submittedAt = deps.now().toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  /** 끝난 단계는 건너뛰고 남은 단계를 이어서 실행한다. 실패하면 UploadFlowError, 중단하면 AbortError. */
  async run(signal: AbortSignal, onEvent: (event: UploadFlowEvent) => void): Promise<UploadFlowResult> {
    if (this.workOrderId === null) {
      onEvent({ type: "stage", stage: "workOrder" });
      await this.createWorkOrder(signal);
    }
    if (this.revision === null) {
      onEvent({ type: "stage", stage: "register" });
      await this.register(signal);
    }
    if (!this.sealed) {
      onEvent({ type: "stage", stage: "upload" });
      await this.upload(signal, onEvent);
      onEvent({ type: "stage", stage: "seal" });
      await this.seal(signal);
    }
    return { workOrderId: this.workOrderId!, submissionRef: this.revision!.submissionRef, revision: this.revision!.submission.revision };
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    return { ...extra, [CONTINUITY_HEADER]: this.input.continuity };
  }

  /** 응답을 읽어 확정 거부·불확실·성공으로 나눈다. 네트워크 오류는 불확실이다. */
  private async send(stage: UploadFlowStage, url: string, init: RequestInit, signal: AbortSignal): Promise<unknown> {
    let response: Response;
    try {
      response = await this.deps.fetch(url, { ...init, signal });
    } catch (error) {
      if (isAbort(error) || signal.aborted) throw error;
      throw new UploadFlowError(stage, true, AMBIGUOUS_MESSAGE);
    }
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      if (isAccountContinuityMismatch(response.status, payload)) throw new UploadFlowError(stage, false, MISMATCH_MESSAGE);
      // 5xx·408·429는 Core가 처리한 뒤 유실됐을 수 있어 확정 거부로 말하지 않는다.
      const definite = response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429;
      throw new UploadFlowError(stage, !definite, definite ? definiteMessage(stage, response.status) : AMBIGUOUS_MESSAGE);
    }
    return payload;
  }

  private async createWorkOrder(signal: AbortSignal): Promise<void> {
    const { siteId, workAreaId, workAreaName } = this.input;
    const payload = await this.send(
      "workOrder",
      `/api/sites/${encodeURIComponent(siteId)}/observation-work-orders`,
      {
        method: "POST",
        headers: this.headers({ "content-type": "application/json", "Idempotency-Key": this.workOrderKey }),
        body: JSON.stringify({
          name: defaultObservationName([workAreaName], this.deps.now()),
          workAreaIds: [workAreaId],
          scheduleId: null,
          executionMode: "EXTERNAL_RECONSTRUCTION",
        }),
      },
      signal,
    );
    const view = payload as { workOrderId?: unknown; siteId?: unknown; workAreaIds?: unknown } | null;
    const sameScope = Array.isArray(view?.workAreaIds) && view.workAreaIds.length === 1 && view.workAreaIds[0] === workAreaId;
    if (!view || typeof view.workOrderId !== "string" || view.workOrderId === "" || view.siteId !== siteId || !sameScope) {
      throw new UploadFlowError("workOrder", true, AMBIGUOUS_MESSAGE);
    }
    this.workOrderId = view.workOrderId;
  }

  private async register(signal: AbortSignal): Promise<void> {
    const workOrderId = this.workOrderId!;
    if (this.body === null) {
      const context = await this.send("register", `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-context`, { method: "GET" }, signal) as
        { workOrderId?: unknown; expectedEpochId?: unknown } | null;
      if (!context || context.workOrderId !== workOrderId || typeof context.expectedEpochId !== "string" || context.expectedEpochId === "") {
        throw new UploadFlowError("register", true, AMBIGUOUS_MESSAGE);
      }
      const built = buildSimpleUploadBody({
        submissionId: this.submissionId,
        expectedEpochId: context.expectedEpochId,
        submittedAt: this.submittedAt,
        startedLocal: this.input.startedLocal,
        endedLocal: this.input.endedLocal,
        files: this.input.files,
      });
      if (!built.ok) throw new UploadFlowError("register", false, built.reason);
      this.body = built.body;
    }
    const body = this.body;
    const payload = await this.send(
      "register",
      `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions-v3`,
      { method: "POST", headers: this.headers({ "content-type": "application/json" }), body: JSON.stringify(body) },
      signal,
    );
    const echo = { submissionRef: null, ...declarationEchoOfRequest(body) };
    if (isRevisionViewForAttempt(payload, echo, "REGISTERED")) {
      this.revision = payload;
      return;
    }
    // 응답을 잃은 뒤 같은 신고서를 다시 보내면 이미 봉인된 같은 기록이 돌아올 수 있다.
    if (isRevisionViewForAttempt(payload, echo, "SEALED")) {
      this.revision = payload;
      this.sealed = true;
      return;
    }
    throw new UploadFlowError("register", true, AMBIGUOUS_MESSAGE);
  }

  private revisionBase(): string {
    const revision = this.revision!;
    return `/api/observation-work-orders/${encodeURIComponent(this.workOrderId!)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}`;
  }

  private async upload(signal: AbortSignal, onEvent: (event: UploadFlowEvent) => void): Promise<void> {
    const pending = this.input.files.filter((item) => !this.uploaded.has(item.kind));
    if (pending.length === 0) return;
    const payload = await this.send("upload", `${this.revisionBase()}/upload-grants`, { method: "POST", headers: this.headers() }, signal) as { grants?: unknown } | null;
    const list = payload && Array.isArray(payload.grants) ? payload.grants : null;
    const grants = list !== null && list.every(isUploadGrantView) ? list : null;
    const ids = grants?.map((grant) => grant.artifactId) ?? null;
    const expected = this.input.files.map((item) => item.kind as string);
    if (!grants || !ids || new Set(ids).size !== ids.length || ids.length !== expected.length || !expected.every((id) => ids.includes(id))) {
      throw new UploadFlowError("upload", true, AMBIGUOUS_MESSAGE);
    }
    for (const item of pending) {
      const grant = grants.find((candidate) => candidate.artifactId === item.kind)!;
      onEvent({ type: "progress", kind: item.kind, transferredBytes: 0, totalBytes: item.size });
      try {
        await this.deps.put(grant, item.file, signal, (transferred) => onEvent({ type: "progress", kind: item.kind, transferredBytes: transferred, totalBytes: item.size }));
      } catch (error) {
        if (isAbort(error) || signal.aborted) throw error;
        throw new UploadFlowError("upload", true, "파일을 올리다 멈췄습니다. 다시 시도하면 이 파일부터 다시 올립니다.");
      }
      this.uploaded.add(item.kind);
      onEvent({ type: "fileDone", kind: item.kind });
    }
  }

  private async seal(signal: AbortSignal): Promise<void> {
    const payload = await this.send("seal", `${this.revisionBase()}/seal`, { method: "POST", headers: this.headers() }, signal);
    const echo = { submissionRef: this.revision!.submissionRef, ...declarationEchoOfRequest(this.body!) };
    if (!isRevisionViewForAttempt(payload, echo, "SEALED")) throw new UploadFlowError("seal", true, AMBIGUOUS_MESSAGE);
    this.sealed = true;
  }
}
