"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { FilePickerField } from "@/components/ui/FilePickerField";
import { ExternalSanitizedOrthophoto } from "@/app/field/ExternalSanitizedOrthophoto";
import { ExternalEvidencePanel } from "@/app/field/ExternalEvidencePanel";
import { presentExternalInspectionStatus } from "@/app/field/external-reconstruction-status";
import {
  ExternalResultWorkflowPanel,
  type ExternalRelativeVolumeDecision,
  type TrustedExternalResultLink,
} from "@/app/field/ExternalResultWorkflowPanel";
import { putExternalReconstructionFile } from "@/lib/external-reconstruction-upload";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatNumberKo } from "@/lib/number-format";
import { ExternalHeaderRecognition, type HeaderRecognitionState } from "@/app/field/ExternalHeaderRecognition";
import { readGeoTiffHeader, recognizeGeoTiffHeader } from "@/lib/geo/geotiff-header";
import {
  seoulDateTimeLocalToUtc,
  type ExternalArtifactKind,
} from "@/lib/external-reconstruction-submission";
import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";

type HashResult = { file: File; sha256: string; size: number };
type ArtifactDeclaration = { artifactId: ExternalArtifactKind; kind: ExternalArtifactKind; fileName: string; format: "GeoTIFF"; contentType: "application/octet-stream"; declaredSha256: string; declaredSizeBytes: number; declaredCrs: string | null; declaredVerticalReference: null; declaredGsdM: null };
type Revision = { submissionRef: string; submission: { submissionId?: string; revision: number; observationEpochId?: string; producerDeclaration?: { softwareName?: string; softwareVersion?: string }; submittedAt?: string; artifacts?: { artifactId: "ortho" | "dsm"; kind: "ortho" | "dsm"; fileName: string; declaredSha256: string; declaredSizeBytes: number }[] }; state: "REGISTERED" | "SEALED" };
type FrozenAttempt = { requestBody: Readonly<{ submissionId: string; expectedEpochId: string; submittedAt: string; softwareName: string; softwareVersion: string; captureStartedAt: string | null; captureEndedAt: string | null; artifacts: readonly ArtifactDeclaration[] }>; bindings: readonly HashResult[] };
type InspectionLoad =
  | { phase: "loading" | "error"; previous: ExternalArtifactInspectionView | null }
  | { phase: "ready"; view: ExternalArtifactInspectionView };
type UploadProgress = { artifactId: ExternalArtifactKind; transferredBytes: number; totalBytes: number; phase: "uploading" | "uploaded" };

const AUTO_INSPECTION_REFRESH_DELAY_MS = 5_000;
const AUTO_INSPECTION_REFRESH_BUDGET = 6;

function retainedInspectionView(load: InspectionLoad | undefined): ExternalArtifactInspectionView | null {
  return load?.phase === "ready" ? load.view : load?.previous ?? null;
}

function utcSeconds(): string { return new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); }
function attemptId(): string { return `console-${crypto.randomUUID()}`; }
function formatFileSize(size: number): string {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${formatNumberKo(size / (1024 * 1024), 1)} MB`;
}
function abortError(): DOMException { return new DOMException("Operation was aborted", "AbortError"); }
function isAbortError(error: unknown): boolean { return error instanceof DOMException && error.name === "AbortError"; }

function inspectionKey(revision: Revision): string { return `${revision.submissionRef}:${revision.submission.revision}`; }

function isExternalArtifactInspectionView(value: unknown): value is ExternalArtifactInspectionView {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  const inspection = candidate.inspection;
  const display = candidate.display;
  return (candidate.registrationState === "REGISTERED" || candidate.registrationState === "SEALED") &&
    (candidate.sealState === "UNSEALED" || candidate.sealState === "SEALED") &&
    !!inspection && typeof inspection === "object" && typeof (inspection as Record<string, unknown>).state === "string" &&
    !!display && typeof display === "object" && typeof (display as Record<string, unknown>).state === "string";
}

async function hashFile(file: File, workers: Set<Worker>, onProgress: (bytes: number) => void, signal: AbortSignal): Promise<HashResult> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("../../lib/workers/file-sha256.worker.ts", import.meta.url));
    let settled = false;
    let onAbort: () => void = () => undefined;
    const finish = () => {
      workers.delete(worker);
      worker.terminate();
      signal.removeEventListener("abort", onAbort);
    };
    const settle = (result: { value: HashResult } | { error: Error }) => {
      if (settled) return;
      settled = true;
      finish();
      if ("error" in result) reject(result.error);
      else resolve(result.value);
    };
    onAbort = () => settle({ error: abortError() });
    workers.add(worker);
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) {
      onAbort();
      return;
    }
    const id = crypto.randomUUID();
    worker.onmessage = ({ data }) => {
      if (data.id !== id) return;
      if (typeof data.progress === "number") onProgress(data.progress);
      if (data.error) settle({ error: new Error(data.error) });
      if (data.sha256) settle({ value: { file, sha256: data.sha256, size: data.size } });
    };
    worker.onerror = () => settle({ error: new Error("file hashing failed") });
    worker.postMessage({ id, file, chunkBytes: 1024 * 1024 });
  });
}

function artifact(kind: ExternalArtifactKind, value: HashResult, crs: string): ArtifactDeclaration {
  // AX-3: 헤더에서 읽었거나 운영자가 고친 좌표계는 고객 신고일 뿐이다. 빈 칸은 신고하지 않는다.
  const declaredCrs = crs.trim() === "" ? null : crs.trim();
  return { artifactId: kind, kind, fileName: value.file.name, format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: value.sha256, declaredSizeBytes: value.size, declaredCrs, declaredVerticalReference: null, declaredGsdM: null };
}

async function recognizeHeader(file: File, signal: AbortSignal): Promise<HeaderRecognitionState> {
  try {
    return { status: "recognized", value: recognizeGeoTiffHeader(await readGeoTiffHeader(file, signal)) };
  } catch (error) {
    if (isAbortError(error)) throw error;
    return { status: "not-geotiff" };
  }
}

function exactBindingsMatch(expected: NonNullable<Revision["submission"]["artifacts"]>, actual: readonly ArtifactDeclaration[]): boolean {
  return expected.length === actual.length && expected.every((item) => {
    const selected = actual.find((candidate) => candidate.kind === item.kind);
    return selected !== undefined && selected.declaredSha256 === item.declaredSha256 && selected.declaredSizeBytes === item.declaredSizeBytes;
  });
}

function ExternalReconstructionPanelState({ workOrderId, siteId = "", expectedEpochId, canWrite, permissions, initialReport, requiresCaptureInterval = false, newIntentAllowed = true }: { workOrderId: string; siteId?: string; expectedEpochId: string | null; canWrite: boolean; permissions?: readonly string[]; initialReport?: TrustedExternalResultLink; requiresCaptureInterval?: boolean; newIntentAllowed?: boolean }) {
  const workers = useRef(new Set<Worker>());
  const scope = useRef(0);
  const listAbort = useRef<AbortController | null>(null);
  const inspectionAbort = useRef(new Map<string, AbortController>());
  const hashAbort = useRef<AbortController | null>(null);
  const submissionAbort = useRef<AbortController | null>(null);
  const inspectionAutoRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inspectionAutoRefreshBudget = useRef(0);
  const inspectionAutoRefreshInFlight = useRef(false);
  const [submissionId, setSubmissionId] = useState(attemptId);
  const [submittedAt, setSubmittedAt] = useState(utcSeconds);
  const [hashing, setHashing] = useState(false);
  const [hashProgress, setHashProgress] = useState<number | null>(null);
  const [softwareName, setSoftwareName] = useState("");
  const [softwareVersion, setSoftwareVersion] = useState("");
  const [captureStartedLocal, setCaptureStartedLocal] = useState("");
  const [captureEndedLocal, setCaptureEndedLocal] = useState("");
  const [captureIntervalTouched, setCaptureIntervalTouched] = useState(false);
  const [ortho, setOrtho] = useState<HashResult | null>(null);
  const [dsm, setDsm] = useState<HashResult | null>(null);
  const [headers, setHeaders] = useState<Partial<Record<ExternalArtifactKind, HeaderRecognitionState>>>({});
  const [declaredCrs, setDeclaredCrs] = useState<Record<ExternalArtifactKind, string>>({ ortho: "", dsm: "" });
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [inspectionByRevision, setInspectionByRevision] = useState<Map<string, InspectionLoad>>(new Map());
  const [inspectionAutoRefreshStopped, setInspectionAutoRefreshStopped] = useState(false);
  const [visibleDisplay, setVisibleDisplay] = useState<string | null>(null);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [resume, setResume] = useState<Revision | null>(null);
  const [frozenAttempt, setFrozenAttempt] = useState<FrozenAttempt | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [relativeVolumeDecision, setRelativeVolumeDecision] = useState<ExternalRelativeVolumeDecision | null>(null);
  const [singleVolumeDecision, setSingleVolumeDecision] = useState<ExternalRelativeVolumeDecision | null>(null);
  const [documentVisible, setDocumentVisible] = useState(true);

  const captureStartedAt = captureStartedLocal ? seoulDateTimeLocalToUtc(captureStartedLocal) : null;
  const captureEndedAt = captureEndedLocal ? seoulDateTimeLocalToUtc(captureEndedLocal) : null;
  const captureIntervalValid = captureStartedLocal === "" && captureEndedLocal === ""
    ? !requiresCaptureInterval
    : captureStartedAt !== null && captureEndedAt !== null && captureStartedAt < captureEndedAt;

  const currentScope = useCallback((value: number) => scope.current === value, []);
  const loadInspection = useCallback(async (
    revision: Revision,
    requestScope = scope.current,
    { automatic = false }: { automatic?: boolean } = {},
  ) => {
    const key = inspectionKey(revision);
    inspectionAbort.current.get(key)?.abort();
    const controller = new AbortController();
    inspectionAbort.current.set(key, controller);
    if (currentScope(requestScope)) setInspectionByRevision((current) => {
      const next = new Map(current);
      next.set(key, { phase: "loading", previous: retainedInspectionView(current.get(key)) });
      return next;
    });
    try {
      const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/inspection`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("inspection could not be loaded");
      const view: unknown = await response.json();
      if (!isExternalArtifactInspectionView(view)) throw new Error("inspection payload is malformed");
      if (!currentScope(requestScope) || inspectionAbort.current.get(key) !== controller) return;
      setInspectionByRevision((current) => new Map(current).set(key, { phase: "ready", view }));
    } catch (error) {
      if (isAbortError(error) || !currentScope(requestScope) || inspectionAbort.current.get(key) !== controller) return;
      setInspectionByRevision((current) => {
        const next = new Map(current);
        next.set(key, { phase: "error", previous: retainedInspectionView(current.get(key)) });
        return next;
      });
      if (automatic) setInspectionAutoRefreshStopped(true);
    } finally {
      if (inspectionAbort.current.get(key) === controller) inspectionAbort.current.delete(key);
    }
  }, [currentScope, workOrderId]);
  const load = useCallback(async (requestScope = scope.current) => {
    listAbort.current?.abort();
    const controller = new AbortController();
    listAbort.current = controller;
    if (currentScope(requestScope)) setListState("loading");
    try {
      const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions`, { signal: controller.signal });
      if (!response.ok) throw new Error("declarations could not be listed");
      const result = await response.json() as { submissions: Revision[] };
      if (!currentScope(requestScope) || listAbort.current !== controller) return;
      setRevisions(result.submissions);
      setInspectionByRevision(new Map());
      setInspectionAutoRefreshStopped(false);
      setVisibleDisplay(null);
      void Promise.all(result.submissions.map((revision) => loadInspection(revision, requestScope)));
      setListState("ready");
    } catch (error) {
      if (isAbortError(error) || !currentScope(requestScope) || listAbort.current !== controller) return;
      setListState("error");
    } finally {
      if (listAbort.current === controller) listAbort.current = null;
    }
  }, [currentScope, loadInspection, workOrderId]);

  // The keyed parent below remounts for a new work order, so this effect owns one scope only.
  useEffect(() => {
    const requestScope = scope.current + 1;
    scope.current = requestScope;
    const workerSet = workers.current;
    const inspectionControllers = inspectionAbort.current;
    void load(requestScope);
    return () => {
      if (!currentScope(requestScope)) return;
      scope.current += 1;
      listAbort.current?.abort();
      inspectionControllers.forEach((controller) => controller.abort());
      inspectionControllers.clear();
      hashAbort.current?.abort();
      submissionAbort.current?.abort();
      if (inspectionAutoRefreshTimer.current !== null) clearTimeout(inspectionAutoRefreshTimer.current);
      inspectionAutoRefreshTimer.current = null;
      listAbort.current = null;
      hashAbort.current = null;
      submissionAbort.current = null;
      workerSet.forEach((worker) => worker.terminate());
      workerSet.clear();
    };
  }, [currentScope, load]);

  useEffect(() => {
    const updateVisibility = () => setDocumentVisible(document.visibilityState !== "hidden");
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    if (inspectionAutoRefreshTimer.current !== null) {
      clearTimeout(inspectionAutoRefreshTimer.current);
      inspectionAutoRefreshTimer.current = null;
    }
    const active = revisions.filter((revision) => {
      const load = inspectionByRevision.get(inspectionKey(revision));
      const view = retainedInspectionView(load);
      return view !== null && presentExternalInspectionStatus(view).autoRefresh;
    });
    if (!documentVisible || inspectionAutoRefreshStopped || active.length === 0 || inspectionAutoRefreshBudget.current >= AUTO_INSPECTION_REFRESH_BUDGET) return;
    inspectionAutoRefreshTimer.current = setTimeout(() => {
      inspectionAutoRefreshTimer.current = null;
      if (document.visibilityState === "hidden" || inspectionAutoRefreshInFlight.current) return;
      inspectionAutoRefreshInFlight.current = true;
      inspectionAutoRefreshBudget.current += 1;
      void Promise.all(active.map((revision) => loadInspection(revision, scope.current, { automatic: true }))).finally(() => {
        inspectionAutoRefreshInFlight.current = false;
      });
    }, AUTO_INSPECTION_REFRESH_DELAY_MS);
    return () => {
      if (inspectionAutoRefreshTimer.current !== null) {
        clearTimeout(inspectionAutoRefreshTimer.current);
        inspectionAutoRefreshTimer.current = null;
      }
    };
  }, [documentVisible, inspectionAutoRefreshStopped, inspectionByRevision, loadInspection, revisions]);

  const cancelHash = () => {
    const controller = hashAbort.current;
    if (!controller) return;
    hashAbort.current = null;
    controller.abort();
    setHashing(false);
    setHashProgress(null);
  };

  const select = async (kind: ExternalArtifactKind, file?: File) => {
    if (!file || hashing || frozenAttempt || (!newIntentAllowed && !resume)) return;
    const requestScope = scope.current;
    const controller = new AbortController();
    hashAbort.current?.abort();
    hashAbort.current = controller;
    setHashing(true);
    setHashProgress(0);
    try {
      const [result, header] = await Promise.all([
        hashFile(file, workers.current, setHashProgress, controller.signal),
        recognizeHeader(file, controller.signal),
      ]);
      if (!currentScope(requestScope) || hashAbort.current !== controller) return;
      if (kind === "ortho") {
        if (ortho && (ortho.sha256 !== result.sha256 || ortho.size !== result.size)) {
          setSubmissionId(attemptId());
          setSubmittedAt(utcSeconds());
          setDsm(null);
          setHeaders((current) => ({ ortho: current.ortho }));
          setDeclaredCrs((current) => ({ ...current, dsm: "" }));
        }
        setOrtho(result);
      } else {
        setDsm(result);
      }
      setHeaders((current) => ({ ...current, [kind]: header }));
      if (!resume) {
        const recognized = header.status === "recognized" ? header.value : null;
        setDeclaredCrs((current) => ({ ...current, [kind]: recognized?.declaredCrs ?? "" }));
        const producer = recognized?.producer;
        if (producer) {
          // 운영자가 이미 적은 값은 덮지 않는다. 빈 칸만 헤더 값으로 채운다.
          setSoftwareName((current) => (current.trim() ? current : producer.name));
          if (producer.version) setSoftwareVersion((current) => (current.trim() ? current : producer.version ?? ""));
        }
      }
      setMessage(null);
    } catch (error) {
      if (!isAbortError(error) && currentScope(requestScope) && hashAbort.current === controller) setMessage("파일 정보를 확인하지 못했습니다.");
    } finally {
      if (hashAbort.current === controller) {
        hashAbort.current = null;
        if (currentScope(requestScope)) {
          setHashing(false);
          setHashProgress(null);
        }
      }
    }
  };

  const selectResume = (revision: Revision) => {
    if (busy || hashing) return;
    setFrozenAttempt(null);
    setResume(revision);
    setOrtho(null);
    setDsm(null);
    setSoftwareName(revision.submission.producerDeclaration?.softwareName ?? "");
    setSoftwareVersion(revision.submission.producerDeclaration?.softwareVersion ?? "");
    setMessage("등록된 파일과 같은 파일을 다시 선택하세요.");
  };

  const startNewAttempt = () => {
    if (busy || hashing) return;
    if (!newIntentAllowed) {
      setMessage("업무 종료 상태에서는 새 산출물 등록을 시작할 수 없습니다.");
      return;
    }
    setResume(null);
    setFrozenAttempt(null);
    setSubmissionId(attemptId());
    setSubmittedAt(utcSeconds());
    setMessage(null);
  };

  const freezeCurrentAttempt = (): FrozenAttempt | null => {
    if (!ortho || !expectedEpochId || !softwareName.trim() || !softwareVersion.trim() || !captureIntervalValid) return null;
    const artifacts = Object.freeze([artifact("ortho", ortho, declaredCrs.ortho), ...(dsm ? [artifact("dsm", dsm, declaredCrs.dsm)] : [])]);
    const requestBody = Object.freeze({ submissionId, expectedEpochId, submittedAt, softwareName: softwareName.trim(), softwareVersion: softwareVersion.trim(), captureStartedAt, captureEndedAt, artifacts });
    return Object.freeze({ requestBody, bindings: Object.freeze([ortho, ...(dsm ? [dsm] : [])]) });
  };

  const submit = async () => {
    if (!ortho || hashing || busy) return;
    let revision = resume;
    let bindings: readonly HashResult[];
    let attempt = frozenAttempt;
    if (revision) {
      // 재개는 종류·해시·크기만 대조한다(이미 등록된 신고를 다시 보내지 않는다).
      const selectedArtifacts = [artifact("ortho", ortho, ""), ...(dsm ? [artifact("dsm", dsm, "")] : [])];
      const expectedArtifacts = revision.submission.artifacts ?? [];
      if (!exactBindingsMatch(expectedArtifacts, selectedArtifacts)) {
        setMessage("선택한 파일이 등록된 선언의 종류, 해시 또는 크기와 일치하지 않습니다.");
        return;
      }
      bindings = [ortho, ...(dsm ? [dsm] : [])];
    } else {
      if (!attempt) {
        if (!newIntentAllowed) {
          setMessage("업무 종료 상태에서는 새 산출물 등록을 시작할 수 없습니다.");
          return;
        }
        if (!captureIntervalValid) {
          setMessage("촬영 시작과 종료 시각을 한국 표준시 기준으로 모두 입력하고 순서를 확인하세요.");
          return;
        }
        attempt = freezeCurrentAttempt();
        if (!attempt) return;
        setFrozenAttempt(attempt);
      }
      bindings = attempt.bindings;
    }

    const requestScope = scope.current;
    const controller = new AbortController();
    submissionAbort.current = controller;
    setBusy(true);
    setUploadProgress(null);
    setMessage(null);
    try {
      if (!revision) {
        const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(attempt!.requestBody), signal: controller.signal });
        if (!response.ok) throw new Error("registration failed");
        revision = await response.json() as Revision;
      }
      if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      const grantsResponse = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/upload-grants`, { method: "POST", signal: controller.signal });
      if (!grantsResponse.ok) throw new Error("grant failed");
      const grants = (await grantsResponse.json()).grants as { artifactId: string; uploadUrl: string; requiredHeaders: Record<string, string> }[];
      const uploadBindings: Array<{ artifactId: ExternalArtifactKind; value: HashResult }> = [
        { artifactId: "ortho", value: bindings[0]! },
        ...(bindings.length === 2 ? [{ artifactId: "dsm" as const, value: bindings[1]! }] : []),
      ];
      for (const { artifactId, value } of uploadBindings) {
        const grant = grants.find((item) => item.artifactId === artifactId);
        if (!grant) throw new Error("missing upload grant");
        setUploadProgress({ artifactId, transferredBytes: 0, totalBytes: value.size, phase: "uploading" });
        await putExternalReconstructionFile(grant, value.file, controller.signal, (transferredBytes) => {
          if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
          setUploadProgress({ artifactId, transferredBytes, totalBytes: value.size, phase: transferredBytes === value.size ? "uploaded" : "uploading" });
        });
        if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      }
      const seal = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/seal`, { method: "POST", signal: controller.signal });
      if (!seal.ok) throw new Error("seal failed");
      if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      setMessage("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
      await load(requestScope);
    } catch (error) {
      if (!isAbortError(error) && currentScope(requestScope) && submissionAbort.current === controller) setMessage("산출물 등록을 완료하지 못했습니다. 목록을 다시 확인하세요.");
    } finally {
      if (submissionAbort.current === controller) {
        submissionAbort.current = null;
        if (currentScope(requestScope)) setBusy(false);
      }
    }
  };

  const cancelSubmission = () => {
    const controller = submissionAbort.current;
    if (!controller) return;
    submissionAbort.current = null;
    controller.abort();
    setBusy(false);
    setUploadProgress(null);
    setMessage("등록을 중단했습니다.");
  };

  const canSubmit = Boolean(ortho) && !busy && !hashing
    && (Boolean(resume) || Boolean(frozenAttempt) || Boolean(newIntentAllowed && expectedEpochId && softwareName.trim() && softwareVersion.trim() && captureIntervalValid));
  const formIsFrozen = Boolean(frozenAttempt || resume);

  const volumeDecisionReceiver = (store: (decision: ExternalRelativeVolumeDecision | null) => void) => (value: {
    decisionId: string;
    decisionDigest?: string;
    verdict: string;
    reasons: string[];
    remediations: string[];
  } | null) => {
    if (!value || !value.decisionDigest || (value.verdict !== "ELIGIBLE" && value.verdict !== "RESTRICTED" && value.verdict !== "BLOCKED")) {
      store(null);
      return;
    }
    store({
      decisionId: value.decisionId,
      decisionDigest: value.decisionDigest,
      verdict: value.verdict,
      reasons: value.reasons,
      remediations: value.remediations,
    });
  };
  const receiveRelativeVolumeDecision = volumeDecisionReceiver(setRelativeVolumeDecision);
  const receiveSingleVolumeDecision = volumeDecisionReceiver(setSingleVolumeDecision);

  return <><section id="external-submissions" className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 text-[13px]">
    <div><h2 className="text-[16px] font-bold">재구성 산출물 등록</h2><p className="text-ink-2">파일을 선택해 정보를 확인한 뒤 등록합니다. 파일 형식과 측정 적합성은 등록 후 별도로 확인합니다.</p></div>
    {!newIntentAllowed && <p className="rounded-lg border border-line bg-sunk px-3 py-2 leading-5 text-ink-2">업무 종료 상태입니다. 새 산출물 등록은 시작할 수 없지만, 이미 등록한 파일의 업로드·봉인 상태와 결과는 계속 확인할 수 있습니다.</p>}
    {canWrite && <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" inlineNotice={false} reason="노트북에서 같은 계정으로 이 작업 상세를 열어 정사영상·DSM 등록을 이어가세요.">
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 font-semibold">재구성 소프트웨어 이름<input className="input" aria-label="재구성 소프트웨어 이름" value={softwareName} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setSoftwareName(event.target.value)} /></label>
        <label className="flex flex-col gap-1 font-semibold">재구성 소프트웨어 버전<input className="input" aria-label="재구성 소프트웨어 버전" value={softwareVersion} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setSoftwareVersion(event.target.value)} /></label>
        <fieldset className="grid gap-2 rounded-lg border border-line bg-sunk p-3" disabled={busy || hashing || formIsFrozen || !newIntentAllowed}>
          <legend className="px-1 font-semibold">촬영 시각 (한국 표준시)</legend>
          <p className="text-[12px] text-ink-2">{requiresCaptureInterval ? "이 외부 등록에는 시작과 종료 시각이 필요합니다." : "알고 있는 경우에만 시작과 종료 시각을 함께 입력하세요."}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1">시작<input className="input" aria-label="촬영 시작 시각 (한국 표준시)" type="datetime-local" step="1" value={captureStartedLocal} onChange={(event) => { setCaptureIntervalTouched(true); setCaptureStartedLocal(event.target.value); }} />
              {captureStartedAt && <span className="text-[12px] text-ink-muted">선택: {formatKoreanDateTime(captureStartedAt, { dateStyle: "short", timeStyle: "short" })}</span>}
            </label>
            <label className="flex flex-col gap-1">종료<input className="input" aria-label="촬영 종료 시각 (한국 표준시)" type="datetime-local" step="1" value={captureEndedLocal} onChange={(event) => { setCaptureIntervalTouched(true); setCaptureEndedLocal(event.target.value); }} />
              {captureEndedAt && <span className="text-[12px] text-ink-muted">선택: {formatKoreanDateTime(captureEndedAt, { dateStyle: "short", timeStyle: "short" })}</span>}
            </label>
          </div>
          {captureIntervalTouched && !captureIntervalValid && <p role="alert" className="text-[12px] text-high-ink">시작과 종료를 모두 입력하고, 종료가 시작보다 늦은지 확인하세요.</p>}
        </fieldset>
        <FilePickerField
          label="정사영상 (필수)"
          ariaLabel="정사영상 GeoTIFF"
          accept=".tif,.tiff"
          disabled={busy || hashing || Boolean(frozenAttempt) || (!newIntentAllowed && !resume)}
          onSelect={(file) => void select("ortho", file ?? undefined)}
          selectedFileName={ortho?.file.name ?? null}
        />
        {ortho && headers.ortho && <ExternalHeaderRecognition slot="ortho" state={headers.ortho} crs={declaredCrs.ortho} crsLocked={busy || hashing || formIsFrozen || !newIntentAllowed} resumingRegistered={Boolean(resume)} onCrsChange={(value) => setDeclaredCrs((current) => ({ ...current, ortho: value }))} />}
        <FilePickerField
          label="DSM (선택)"
          ariaLabel="DSM GeoTIFF"
          accept=".tif,.tiff"
          disabled={busy || hashing || Boolean(frozenAttempt) || !ortho || (!newIntentAllowed && !resume)}
          onSelect={(file) => void select("dsm", file ?? undefined)}
          selectedFileName={dsm?.file.name ?? null}
        />
        {dsm && headers.dsm && <ExternalHeaderRecognition slot="dsm" state={headers.dsm} crs={declaredCrs.dsm} crsLocked={busy || hashing || formIsFrozen || !newIntentAllowed} resumingRegistered={Boolean(resume)} onCrsChange={(value) => setDeclaredCrs((current) => ({ ...current, dsm: value }))} />}
        {newIntentAllowed && (resume || frozenAttempt) && <button className="btn w-fit" disabled={busy || hashing} onClick={startNewAttempt}>새 선언으로 전환</button>}
        {hashing && <p role="status" className="text-ink-2">파일 확인 중: {formatBytesKo(hashProgress ?? 0)}</p>}
        {hashing && <button className="btn w-fit" onClick={cancelHash}>파일 확인 취소</button>}
        <p className="text-ink-2">{ortho ? `정사영상 ${formatFileSize(ortho.size)} 확인 완료` : "정사영상을 선택하세요."}{dsm ? ` · DSM ${formatFileSize(dsm.size)} 확인 완료` : ""}</p>
        <button className="btn w-fit" disabled={!canSubmit} onClick={() => void submit()}>{busy ? "산출물 등록 중" : "산출물 등록하기"}</button>
        {uploadProgress && <p role="status" className="text-ink-2">{uploadProgress.artifactId === "ortho" ? "정사영상" : "DSM"} {uploadProgress.phase === "uploaded" ? "파일 전송 완료" : "파일 전송 중"}: {formatBytesKo(uploadProgress.transferredBytes)} / {formatBytesKo(uploadProgress.totalBytes)} {uploadProgress.phase === "uploading" && " · 전송 시간이나 비율은 추정하지 않습니다."}</p>}
        {busy && <button className="btn w-fit" onClick={cancelSubmission}>등록 중단</button>}
        {message && <p role="status" className="text-ink-2">{message}</p>}
      </div>
    </ResponsiveActionBoundary>}
    {!canWrite && <p className="text-ink-2">조회 전용 계정입니다.</p>}
    {listState === "loading" && <p role="status" className="text-ink-2">선언 목록을 불러오는 중입니다.</p>}
    {listState === "error" && <div role="alert" className="flex flex-col items-start gap-2 text-ink-2"><p>선언 목록을 불러오지 못했습니다.</p><button className="btn w-fit" onClick={() => void load()}>목록 다시 시도</button></div>}
    {listState === "ready" && <ul className="flex flex-col gap-2 text-ink-2">{revisions.length === 0 ? <li>등록된 외부 산출물이 없습니다.</li> : revisions.map((revision) => {
      const key = inspectionKey(revision);
      const inspection = inspectionByRevision.get(key);
      const inspectionView = retainedInspectionView(inspection);
      const presentation = inspectionView !== null ? presentExternalInspectionStatus(inspectionView) : null;
      const display = inspectionView !== null && presentation?.displayReady === true
        && typeof inspectionView.display.sanitizedDisplayRef === "string" && typeof inspectionView.display.receiptDigest === "string"
        ? {
          sanitizedDisplayRef: inspectionView.display.sanitizedDisplayRef,
          receiptDigest: inspectionView.display.receiptDigest,
        }
        : null;
      return <li key={key} className="rounded-lg border border-line px-3 py-2"><p>{revision.submission.artifacts?.map((item) => item.fileName).join(", ") || "외부 산출물"} · {revision.submission.producerDeclaration?.softwareName ?? "재구성 소프트웨어"} {revision.submission.producerDeclaration?.softwareVersion ?? ""} · {presentation?.title ?? (inspection?.phase === "error" ? "검사 상태를 불러오지 못했습니다." : "검사 상태 확인 중")}</p>
        {presentation && <><p className="mt-1 text-[12px] leading-5 text-ink-2">{presentation.detail}</p><p className="mt-1 text-[12px] leading-5 text-ink-muted">다음: {presentation.nextAction}</p>{presentation.artifactReasons.length > 0 && <ul className="mt-1 list-disc pl-5 text-[12px] leading-5 text-high-ink">{presentation.artifactReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}</>}
        {inspection?.phase === "loading" && inspectionView !== null && <p role="status" className="mt-1 text-[12px] text-ink-2">마지막으로 확인한 검사 상태를 유지한 채 업데이트를 확인하고 있습니다.</p>}
        {inspection?.phase === "error" && inspectionView !== null && <p role="alert" className="mt-1 text-[12px] text-high-ink">검사 상태 업데이트를 확인하지 못했습니다. 마지막으로 확인한 상태를 표시합니다. 새로고침으로 다시 시도하세요.</p>}
        {inspectionAutoRefreshStopped && presentation?.autoRefresh && <p role="status" className="mt-1 text-[12px] text-ink-2">자동 상태 확인을 멈췄습니다. 마지막으로 확인한 검사 상태를 표시합니다. 새로고침으로 다시 확인하세요.</p>}
        <div className="mt-2 flex flex-wrap gap-2"><button className="btn" onClick={() => { inspectionAutoRefreshBudget.current = 0; setInspectionAutoRefreshStopped(false); void loadInspection(revision); }}>검사 상태 새로고침</button>{display && <button className="btn" onClick={() => setVisibleDisplay((current) => current === key ? null : key)}>{visibleDisplay === key ? "정제 정사영상 닫기" : "정제 정사영상 표시"}</button>}{canWrite && revision.state === "REGISTERED" && <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" reason="등록 중인 외부 산출물을 다시 이어가는 일은 노트북 이상의 화면에서만 진행합니다."><button className="btn" onClick={() => selectResume(revision)}>등록된 선언 재개</button></ResponsiveActionBoundary>}</div>
        {display && visibleDisplay === key && <ExternalSanitizedOrthophoto workOrderId={workOrderId} submissionRef={revision.submissionRef} revision={revision.submission.revision} sanitizedDisplayRef={display.sanitizedDisplayRef} receiptDigest={display.receiptDigest} onDismiss={() => setVisibleDisplay(null)} />}
        <details className="mt-1 text-[12px] text-ink-2"><summary>전문가 정보</summary><div className="mt-1 break-all"><p>등록 상태: {revision.state}</p>{inspectionView !== null && <><p>검사 상태: {inspectionView.inspection.state}</p><p>표시 상태: {inspectionView.display.state}</p>{inspectionView.inspection.outcome?.map((outcome) => <p key={`${outcome.artifactId}:${outcome.outcome}:${outcome.reason ?? ""}`}>산출물 기록: {outcome.artifactId} · {outcome.outcome}{outcome.reason ? ` · 사유 코드/기록: ${outcome.reason}` : ""}</p>)}</>}</div></details>
      </li>;
    })}</ul>}
  </section><ExternalEvidencePanel workOrderId={workOrderId} siteId={siteId} revisions={revisions} canWrite={canWrite} newIntentAllowed={newIntentAllowed} onRelativeVolumeDecisionChange={receiveRelativeVolumeDecision} onSingleVolumeDecisionChange={receiveSingleVolumeDecision} /><ExternalResultWorkflowPanel workOrderId={workOrderId} siteId={siteId} decision={relativeVolumeDecision} singleVolumeDecision={singleVolumeDecision} initialReport={initialReport} permissions={permissions ?? (canWrite ? ["SITES_WRITE"] : [])} newIntentAllowed={newIntentAllowed} /></>;
}

export function ExternalReconstructionPanel(props: { workOrderId: string; siteId?: string; expectedEpochId: string | null; canWrite: boolean; permissions?: readonly string[]; initialReport?: TrustedExternalResultLink; requiresCaptureInterval?: boolean; newIntentAllowed?: boolean }) {
  return <ExternalReconstructionPanelState key={`${props.workOrderId}:${props.initialReport?.reportRef ?? ""}:${props.initialReport?.reportDigest ?? ""}`} {...props} />;
}
