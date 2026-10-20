"use client";

import { useRouter } from "next/navigation";
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
import { describeExternalBasenameIssue } from "@/lib/external-reconstruction-basename";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatNumberKo } from "@/lib/number-format";
import { formatRegistrationVersion, describeArtifactKinds, submissionStateLabel, describeProducerLine, describeCaptureLine, describeRetentionLine, formatPublisherCalendarDate } from "@/app/field/registration-language";
import { ExternalHeaderRecognition, type HeaderRecognitionState } from "@/app/field/ExternalHeaderRecognition";
import { readGeoTiffHeader, recognizeGeoTiffHeader } from "@/lib/geo/geotiff-header";
import {
  seoulDateTimeLocalToUtc,
  describeV3MetadataIssue,
  isPublisherCalendarDate,
  type ExternalArtifactKind,
  type ExternalV3CaptureBasis,
  type ExternalV3ProducerKnowledge,
  type ExternalV3RetentionLocus,
} from "@/lib/external-reconstruction-submission";
import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";

type HashResult = { file: File; sha256: string; size: number };
type ArtifactDeclaration = { artifactId: ExternalArtifactKind; kind: ExternalArtifactKind; fileName: string; format: "GeoTIFF"; contentType: "application/octet-stream"; declaredSha256: string; declaredSizeBytes: number; declaredCrs: string | null; declaredVerticalReference: null; declaredGsdM: null };
type RevisionSubmission = {
  submissionId?: string; revision: number; observationEpochId?: string;
  contractVersion?: string;
  producerDeclaration?: { softwareName?: string | null; softwareVersion?: string | null; producerKnowledge?: string | null; sourceNote?: string | null };
  inputDeclaration?: {
    captureBasis?: string | null; captureDate?: string | null; captureStartedAt?: string | null; captureEndedAt?: string | null;
    originalRetentionLocus?: string | null; originalRetentionDetail?: string | null;
    upstreamSource?: { sourceUri?: string | null; sourceSha256?: string | null; licenceDeclaration?: string | null; retrievalNote?: string | null } | null;
    derivativeExport?: { toolName?: string | null; toolVersion?: string | null; settingsDigest?: string | null; exportedAt?: string | null; exportNote?: string | null } | null;
  } | null;
  submittedAt?: string;
  artifacts?: { artifactId: "ortho" | "dsm"; kind: "ortho" | "dsm"; fileName: string; declaredSha256: string; declaredSizeBytes: number }[];
};
type Revision = { submissionRef: string; submission: RevisionSubmission; state: "REGISTERED" | "SEALED" };
type FrozenAttempt = { requestBody: Readonly<V3DeclarationBody>; bindings: readonly { slot: ExternalArtifactKind; value: HashResult }[] };
type V3DeclarationBody = {
  submissionId: string; expectedEpochId: string; submittedAt: string;
  producerKnowledge: ExternalV3ProducerKnowledge; softwareName: string | null; softwareVersion: string | null; sourceNote: string | null;
  captureBasis: ExternalV3CaptureBasis; captureStartedAt: string | null; captureEndedAt: string | null; captureDate: string | null;
  originalRetentionLocus: ExternalV3RetentionLocus; originalRetentionDetail: string | null;
  upstreamSource: { sourceUri: string; sourceSha256: string | null; licenceDeclaration: string | null; retrievalNote: string | null } | null;
  derivativeExport: { toolName: string; toolVersion: string; settingsDigest: string | null; exportedAt: string | null; exportNote: string | null } | null;
  artifacts: readonly ArtifactDeclaration[];
};
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

function ExternalReconstructionPanelState({ workOrderId, siteId = "", expectedEpochId, canWrite, permissions, initialReport, requiresCaptureInterval = false, newIntentAllowed = true, workAreaNames }: { workOrderId: string; siteId?: string; expectedEpochId: string | null; canWrite: boolean; permissions?: readonly string[]; initialReport?: TrustedExternalResultLink; requiresCaptureInterval?: boolean; newIntentAllowed?: boolean; workAreaNames?: Readonly<Record<string, string>> }) {
  const router = useRouter();
  const legacyDetails = useRef<HTMLDetailsElement>(null);
  // V1은 보존 기능이지 현재 분석 진입점이 아니다. 기본은 접되 기존 결과·제안
  // 딥링크는 초기 진입과 같은 페이지 이동 모두에서 내용을 드러내야 한다.
  useEffect(() => {
    const revealLegacyTarget = () => {
      const hash = window.location.hash;
      if ((hash === "#external-volume" || hash === "#external-result") && legacyDetails.current) {
        legacyDetails.current.open = true;
        document.getElementById(hash.slice(1))?.scrollIntoView?.({ block: "start" });
      }
    };
    revealLegacyTarget();
    window.addEventListener("hashchange", revealLegacyTarget);
    return () => window.removeEventListener("hashchange", revealLegacyTarget);
  }, []);
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
  const [producerKnowledge, setProducerKnowledge] = useState<ExternalV3ProducerKnowledge>("DECLARED");
  const [sourceNote, setSourceNote] = useState("");
  const [captureBasis, setCaptureBasis] = useState<ExternalV3CaptureBasis>(() => requiresCaptureInterval ? "EXACT_INTERVAL" : "UNKNOWN");
  const [captureStartedLocal, setCaptureStartedLocal] = useState("");
  const [captureEndedLocal, setCaptureEndedLocal] = useState("");
  const [captureDateLocal, setCaptureDateLocal] = useState("");
  const [captureIntervalTouched, setCaptureIntervalTouched] = useState(false);
  const [retentionLocus, setRetentionLocus] = useState<ExternalV3RetentionLocus>("customer_workstation");
  const [retentionDetail, setRetentionDetail] = useState("");
  const [upstreamUri, setUpstreamUri] = useState("");
  const [upstreamSha, setUpstreamSha] = useState("");
  const [upstreamLicence, setUpstreamLicence] = useState("");
  const [upstreamNote, setUpstreamNote] = useState("");
  const [exportToolName, setExportToolName] = useState("");
  const [exportToolVersion, setExportToolVersion] = useState("");
  const [exportSettingsDigest, setExportSettingsDigest] = useState("");
  const [exportedAtLocal, setExportedAtLocal] = useState("");
  const [exportNote, setExportNote] = useState("");
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
  // 등록 기준에 맞지 않는 파일 이름 — 슬롯별로 둔다. 같은 내용의 POST·동결을
  // 막고, 이전에 확인한 선택을 조용히 내보내지 않는다. 유효한 다시 선택·
  // 지우기로만 슬롯마다 푼다.
  const [nameIssues, setNameIssues] = useState<Record<ExternalArtifactKind, { fileName: string; reason: string } | null>>({ ortho: null, dsm: null });
  // 422로 분류된 선언 — 같은 식별자로는 다시 시도해도 접수되지 않는다. 조용히
  // 버리지 않고, 명시적인 새 등록으로만 새 식별자를 만든다.
  const [payloadRejected, setPayloadRejected] = useState(false);
  // 확인된 봉인(seal.ok + 현 범위) — 같은 파일의 반복 업로드·승인을 막는다.
  // 응답 미확인(uncertain)에는 세우지 않고, 명시적인 새 등록·이어하기로만 푼다.
  const [sealedComplete, setSealedComplete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [relativeVolumeDecision, setRelativeVolumeDecision] = useState<ExternalRelativeVolumeDecision | null>(null);
  const [singleVolumeDecision, setSingleVolumeDecision] = useState<ExternalRelativeVolumeDecision | null>(null);
  const [documentVisible, setDocumentVisible] = useState(true);

  const captureStartedAt = captureBasis === "EXACT_INTERVAL" && captureStartedLocal ? seoulDateTimeLocalToUtc(captureStartedLocal) : null;
  const captureEndedAt = captureBasis === "EXACT_INTERVAL" && captureEndedLocal ? seoulDateTimeLocalToUtc(captureEndedLocal) : null;
  // EXACT를 고르면 순서가 맞는 구간이 있어야 한다. 비어 있으면 UNKNOWN을 고른다.
  // DATE_ONLY는 달력 날짜 하나, UNKNOWN은 항상 유효하다.
  const captureValid = captureBasis === "EXACT_INTERVAL"
    ? captureStartedAt !== null && captureEndedAt !== null && captureStartedAt < captureEndedAt
    : captureBasis === "DATE_ONLY"
      ? isPublisherCalendarDate(captureDateLocal)
      : true;

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
    // 이어하기(등록된 참조의 바이트 대조)는 새 신고가 아니라 파일 이름 문법을
    // 적용하지 않는다. 새 등록만 해시 같은 비싼 확인 전에 파일 이름을 검사한다.
    if (!resume) {
      const issue = describeExternalBasenameIssue(file.name);
      if (issue !== null) {
        setNameIssues((current) => ({ ...current, [kind]: { fileName: file.name, reason: issue } }));
        return;
      }
    }
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
        }
        setOrtho(result);
      } else {
        if (dsm && (dsm.sha256 !== result.sha256 || dsm.size !== result.size)) {
          setSubmissionId(attemptId());
          setSubmittedAt(utcSeconds());
        }
        setDsm(result);
      }
      setHeaders((current) => ({ ...current, [kind]: header }));
      setNameIssues((current) => ({ ...current, [kind]: null }));
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
    } finally {      if (hashAbort.current === controller) {
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
    setNameIssues({ ortho: null, dsm: null });
    setSealedComplete(false);
    // 재개는 등록된 신고를 다시 보내지 않으므로 폼 값은 참고용으로만 둔다.
    const knowledge = revision.submission.producerDeclaration?.producerKnowledge;
    setProducerKnowledge(knowledge === "PARTIAL" || knowledge === "UNKNOWN" ? knowledge : "DECLARED");
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
    setPayloadRejected(false);
    setNameIssues({ ortho: null, dsm: null });
    setSealedComplete(false);
    setSubmissionId(attemptId());
    setSubmittedAt(utcSeconds());
    setMessage(null);
  };

  // 슬롯은 서로 독립이다. 한 칸을 지워도 다른 칸의 확인된 선택을 버리지
  // 않는다. 이름 문제도 고친 칸만 푼다.
  const clearSlot = (kind: ExternalArtifactKind) => {
    if (busy || hashing || frozenAttempt) return;
    setNameIssues((current) => ({ ...current, [kind]: null }));
    if (kind === "ortho") {
      setOrtho(null);
      setHeaders((current) => {
        const next = { ...current };
        delete next.ortho;
        return next;
      });
      setDeclaredCrs((current) => ({ ...current, ortho: "" }));
    } else {
      setDsm(null);
      setHeaders((current) => {
        const next = { ...current };
        delete next.dsm;
        return next;
      });
      setDeclaredCrs((current) => ({ ...current, dsm: "" }));
    }
  };

  const metadataIssue = describeV3MetadataIssue({
    producerKnowledge, softwareName, softwareVersion, sourceNote,
    captureBasis, captureDateLocal,
    upstreamUri, upstreamSha,
    exportToolName, exportToolVersion, exportSettingsDigest, exportedAtLocal, exportNote,
  });
  const hasFile = Boolean(ortho || dsm);

  const freezeCurrentAttempt = (): FrozenAttempt | null => {
    if (!hasFile || !expectedEpochId || metadataIssue !== null || !captureValid) return null;
    const name = softwareName.trim();
    const version = softwareVersion.trim();
    const uri = upstreamUri.trim();
    const toolName = exportToolName.trim();
    const toolVersion = exportToolVersion.trim();
    const exportedAt = exportedAtLocal ? seoulDateTimeLocalToUtc(exportedAtLocal) : null;
    const artifacts = Object.freeze([...(ortho ? [artifact("ortho", ortho, declaredCrs.ortho)] : []), ...(dsm ? [artifact("dsm", dsm, declaredCrs.dsm)] : [])]);
    const requestBody = Object.freeze({
      submissionId, expectedEpochId, submittedAt,
      producerKnowledge,
      softwareName: producerKnowledge === "UNKNOWN" ? null : name,
      softwareVersion: producerKnowledge === "DECLARED" ? version : null,
      sourceNote: sourceNote.trim() === "" ? null : sourceNote.trim(),
      captureBasis,
      captureStartedAt, captureEndedAt,
      captureDate: captureBasis === "DATE_ONLY" ? captureDateLocal : null,
      originalRetentionLocus: retentionLocus,
      originalRetentionDetail: retentionDetail.trim() === "" ? null : retentionDetail.trim(),
      upstreamSource: uri === "" ? null : {
        sourceUri: uri,
        sourceSha256: upstreamSha.trim() === "" ? null : upstreamSha.trim(),
        licenceDeclaration: upstreamLicence.trim() === "" ? null : upstreamLicence.trim(),
        retrievalNote: upstreamNote.trim() === "" ? null : upstreamNote.trim(),
      },
      derivativeExport: toolName === "" ? null : {
        toolName, toolVersion,
        settingsDigest: exportSettingsDigest.trim() === "" ? null : exportSettingsDigest.trim(),
        exportedAt,
        exportNote: exportNote.trim() === "" ? null : exportNote.trim(),
      },
      artifacts,
    });
    const bindings = Object.freeze([...(ortho ? [{ slot: "ortho" as const, value: ortho }] : []), ...(dsm ? [{ slot: "dsm" as const, value: dsm }] : [])]);
    return Object.freeze({ requestBody, bindings });
  };

  const submit = async () => {
    if (!hasFile || hashing || busy || sealedComplete) return;
    let revision = resume;
    let bindings: FrozenAttempt["bindings"];
    let attempt = frozenAttempt;
    if (revision) {
      // 재개는 종류·해시·크기만 대조한다(이미 등록된 신고를 다시 보내지 않는다).
      const selectedArtifacts = [...(ortho ? [artifact("ortho", ortho, "")] : []), ...(dsm ? [artifact("dsm", dsm, "")] : [])];
      const expectedArtifacts = revision.submission.artifacts ?? [];
      if (!exactBindingsMatch(expectedArtifacts, selectedArtifacts)) {
        setMessage("선택한 파일이 등록된 자료의 종류, 해시 또는 크기와 일치하지 않습니다.");
        return;
      }
      bindings = [...(ortho ? [{ slot: "ortho" as const, value: ortho }] : []), ...(dsm ? [{ slot: "dsm" as const, value: dsm }] : [])];
    } else {
      // 기준에 맞지 않는 이름·422 분류 선언은 같은 내용으로 보내지 않는다.
      // 슬롯마다 남은 문제가 하나라도 있으면 동결·전송하지 않는다.
      if (nameIssues.ortho || nameIssues.dsm) {
        setMessage("파일 이름이 등록 기준에 맞지 않아 보낼 수 없습니다. 조건에 맞는 복사본을 다시 선택하거나 이전 선택을 지우세요.");
        return;
      }
      if (payloadRejected) {
        setMessage("제출 내용이 등록 기준에 맞지 않아 접수되지 않았습니다. 같은 내용으로는 다시 시도해도 접수되지 않습니다. 새로 등록하기로 새 식별자를 만들어 다시 시도하세요.");
        return;
      }
      if (!attempt) {
        if (!newIntentAllowed) {
          setMessage("업무 종료 상태에서는 새 산출물 등록을 시작할 수 없습니다.");
          return;
        }
        if (metadataIssue !== null) {
          setMessage(metadataIssue);
          return;
        }
        if (!captureValid) {
          setMessage(captureBasis === "DATE_ONLY"
            ? "촬영 날짜만 아는 경우 YYYY-MM-DD 형식의 날짜를 입력하세요."
            : "촬영 시작과 종료 시각을 한국 표준시 기준으로 모두 입력하고 순서를 확인하세요.");
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
        const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions-v3`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(attempt!.requestBody), signal: controller.signal });
        if (!response.ok) {
          // 422는 내용 자체가 기준에 맞지 않는 분류 — 같은 식별자로는 다시
          // 보내지 않는다. 동결된 시도는 버리지 않고 명시적인 새 등록을 둔다.
          if (response.status === 422) {
            setPayloadRejected(true);
            setMessage("제출 내용이 등록 기준에 맞지 않아 접수되지 않았습니다. 같은 내용으로는 다시 시도해도 접수되지 않습니다. 새로 등록하기로 새 식별자를 만들어 파일과 입력값을 확인한 뒤 다시 시도하세요.");
            return;
          }
          throw new Error("registration failed");
        }
        revision = await response.json() as Revision;
      }
      if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      const grantsResponse = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/upload-grants`, { method: "POST", signal: controller.signal });
      if (!grantsResponse.ok) throw new Error("grant failed");
      const grants = (await grantsResponse.json()).grants as { artifactId: string; uploadUrl: string; requiredHeaders: Record<string, string> }[];
      const uploadBindings: Array<{ artifactId: ExternalArtifactKind; value: HashResult }> = bindings.map(({ slot, value }) => ({ artifactId: slot, value }));
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
      // 확인된 봉인에서만 완료로 잠근다. 응답 미확인 경로(throw·중단)는 동결된
      // 시도를 그대로 두고 같은 식별자로 다시 확인할 수 있게 둔다.
      setSealedComplete(true);
      setMessage("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
      await load(requestScope);
      // The server owns the stage and scoped continuation. Refresh only after
      // acknowledged sealing, merging its payload without resetting client drafts.
      if (currentScope(requestScope) && submissionAbort.current === controller) router.refresh();
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

  const canSubmit = hasFile && !busy && !hashing && !sealedComplete && !nameIssues.ortho && !nameIssues.dsm && metadataIssue === null && captureValid
    && (Boolean(resume) || (!payloadRejected && (Boolean(frozenAttempt) || Boolean(newIntentAllowed && expectedEpochId))));
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

  // 유지된 revision이 있으면 새 등록 폼은 펼침 뒤에 둔다. 단, 진행 중·동결된
  // 시도(파일 선택·응답 미확인 재시도·재개·전송 중·안내 문구)는 절대 숨기지
  // 않는다 — compactness보다 시도 보존이 우선이다.
  const hasRetainedRevisions = listState === "ready" && revisions.length > 0;
  const newFormPristine = !formIsFrozen && !busy && !hashing && !uploadProgress && !ortho && !dsm && message === null;
  const collapseNewForm = hasRetainedRevisions && newFormPristine;

  return <><section id="external-submissions" className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 text-[13px]">
    <div><h2 className="text-[16px] font-bold">관측 자료 등록</h2><p className="text-ink-2">외부에서 준비한 파일을 선택해 등록합니다. 파일 검사와 분석에 사용할 수 있는지 확인하는 절차는 별도입니다.</p></div>
    {!newIntentAllowed && <p className="rounded-lg border border-line bg-sunk px-3 py-2 leading-5 text-ink-2">업무 종료 상태입니다. 새 산출물 등록은 시작할 수 없지만, 이미 등록한 파일의 업로드·봉인 상태와 결과는 계속 확인할 수 있습니다.</p>}
    {listState === "loading" && <p role="status" className="text-ink-2">등록 목록을 불러오는 중입니다.</p>}
    {listState === "error" && <div role="alert" className="flex flex-col items-start gap-2 text-ink-2"><p>등록 목록을 불러오지 못했습니다.</p><button className="btn w-fit" onClick={() => void load()}>목록 다시 시도</button></div>}
    {listState === "ready" && <ul className="flex flex-col gap-2 text-ink-2">{revisions.length === 0 ? <li><span>아직 등록된 관측 자료가 없습니다.</span>{" "}자료를 등록하면 파일 제출과 검사 상태를 이곳에서 확인할 수 있습니다.</li> : null}</ul>}
    {!canWrite && <p className="text-ink-2">조회 전용 계정입니다. 등록 자료와 검사 상태를 확인할 수 있습니다.</p>}
    {canWrite && <details open={collapseNewForm ? undefined : true}>
      <summary className="tap-target cursor-pointer font-semibold">새 산출물 등록</summary>
      <div className="mt-3 flex flex-col gap-3">
    {canWrite && <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" inlineNotice={false} reason="노트북에서 같은 계정으로 이 작업 상세를 열어 정사영상·DSM 등록을 이어가세요.">
      <div className="flex flex-col gap-3">
        <fieldset className="grid gap-2 rounded-lg border border-line bg-sunk p-3" disabled={busy || hashing || formIsFrozen || !newIntentAllowed}>
          <legend className="px-1 font-semibold">재구성 소프트웨어</legend>
          <p className="text-[12px] text-ink-2">실제 재구성한 소프트웨어를 아는 대로 선택하세요. ‘unknown’이라고 쓰지 않습니다.</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="재구성 소프트웨어 확인 방식">
            {(["DECLARED", "PARTIAL", "UNKNOWN"] as const).map((option) => (
              <label key={option} className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12px]">
                <input type="radio" name="producer-knowledge" value={option} checked={producerKnowledge === option} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={() => {
                  setProducerKnowledge(option);
                  if (option === "UNKNOWN") { setSoftwareName(""); setSoftwareVersion(""); }
                  if (option === "PARTIAL") { setSoftwareVersion(""); }
                }} />
                {option === "DECLARED" ? "이름과 버전 모두 알고 있음" : option === "PARTIAL" ? "이름만 알고 있음" : "미상"}
              </label>
            ))}
          </div>
          {producerKnowledge !== "UNKNOWN" && <label className="flex flex-col gap-1 font-semibold">재구성 소프트웨어 이름<input className="input" aria-label="재구성 소프트웨어 이름" value={softwareName} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setSoftwareName(event.target.value)} /></label>}
          {producerKnowledge === "DECLARED" && <label className="flex flex-col gap-1 font-semibold">재구성 소프트웨어 버전<input className="input" aria-label="재구성 소프트웨어 버전" value={softwareVersion} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setSoftwareVersion(event.target.value)} /></label>}
          <label className="flex flex-col gap-1 font-semibold">출처 기록 (선택)<input className="input" aria-label="재구성 소프트웨어 출처 기록" value={sourceNote} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setSourceNote(event.target.value)} /></label>
        </fieldset>
        <fieldset className="grid gap-2 rounded-lg border border-line bg-sunk p-3" disabled={busy || hashing || formIsFrozen || !newIntentAllowed}>
          <legend className="px-1 font-semibold">촬영 시점 (한국 표준시)</legend>
          <p className="text-[12px] text-ink-2">{requiresCaptureInterval ? "외부 관측 등록에는 촬영 구간 확인이 권장됩니다. 미상인 경우 그대로 등록되며, 이후 분석·비교 가능 여부는 별도로 확인합니다." : "촬영 방식을 선택하세요. 선택한 방식만 등록에 포함됩니다."}</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="촬영 시점 확인 방식">
            {(["EXACT_INTERVAL", "DATE_ONLY", "UNKNOWN"] as const).map((option) => (
              <label key={option} className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12px]">
                <input type="radio" name="capture-basis" value={option} checked={captureBasis === option} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={() => setCaptureBasis(option)} />
                {option === "EXACT_INTERVAL" ? "정확한 촬영 시각" : option === "DATE_ONLY" ? "촬영 날짜만 확인됨" : "촬영 시점 미상"}
              </label>
            ))}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1">시작<input className="input" aria-label="촬영 시작 시각 (한국 표준시)" type="datetime-local" step="1" value={captureStartedLocal} onChange={(event) => { setCaptureIntervalTouched(true); setCaptureStartedLocal(event.target.value); }} />
              {captureStartedAt && <span className="text-[12px] text-ink-muted">선택: {formatKoreanDateTime(captureStartedAt, { dateStyle: "short", timeStyle: "short" })}</span>}
            </label>
            <label className="flex flex-col gap-1">종료<input className="input" aria-label="촬영 종료 시각 (한국 표준시)" type="datetime-local" step="1" value={captureEndedLocal} onChange={(event) => { setCaptureIntervalTouched(true); setCaptureEndedLocal(event.target.value); }} />
              {captureEndedAt && <span className="text-[12px] text-ink-muted">선택: {formatKoreanDateTime(captureEndedAt, { dateStyle: "short", timeStyle: "short" })}</span>}
            </label>
          </div>
          <label className="flex flex-col gap-1">촬영 날짜 (날짜만 아는 경우)<input className="input" aria-label="촬영 날짜 (YYYY-MM-DD)" type="date" value={captureDateLocal} onChange={(event) => setCaptureDateLocal(event.target.value)} />
            {captureBasis === "DATE_ONLY" && formatPublisherCalendarDate(captureDateLocal) && <span className="text-[12px] text-ink-muted">선택: {formatPublisherCalendarDate(captureDateLocal)} · 시각 미상</span>}
          </label>
          {captureBasis === "UNKNOWN" && <p className="text-[12px] text-ink-2">촬영 시점을 미상으로 등록합니다. 자정 시각 같은 추정값을 넣지 않습니다. 이후 분석·비교 가능 여부는 별도로 확인합니다.</p>}
          {captureBasis === "EXACT_INTERVAL" && captureIntervalTouched && !captureValid && <p role="alert" className="text-[12px] text-high-ink">시작과 종료를 모두 입력하고, 종료가 시작보다 늦은지 확인하세요.</p>}
        </fieldset>
        <fieldset className="grid gap-2 rounded-lg border border-line bg-sunk p-3" disabled={busy || hashing || formIsFrozen || !newIntentAllowed}>
          <legend className="px-1 font-semibold">원본 보관 위치</legend>
          <p className="text-[12px] text-ink-2">원본 사진은 요청하지 않습니다. 등록하는 파일의 원본이 어디에 있는지 아는 대로 선택하세요. 공개 출처에 원본이 있다고 단정하지 마세요.</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="원본 보관 위치">
            {(["customer_workstation", "upstream_source", "unknown"] as const).map((option) => (
              <label key={option} className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12px]">
                <input type="radio" name="original-retention" value={option} checked={retentionLocus === option} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={() => setRetentionLocus(option)} />
                {option === "customer_workstation" ? "고객 작업 장비에 있음" : option === "upstream_source" ? "공개 출처에 있음(확인된 경우만)" : "미상"}
              </label>
            ))}
          </div>
          <label className="flex flex-col gap-1 font-semibold">보관 위치 상세 (선택)<input className="input" aria-label="원본 보관 위치 상세" value={retentionDetail} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setRetentionDetail(event.target.value)} /></label>
        </fieldset>
        <details className="rounded-lg border border-line bg-sunk p-3 text-[12px]">
          <summary className="tap-target cursor-pointer font-semibold">원본 공개 출처 (선택)</summary>
          <p className="mt-1 leading-5 text-ink-2">공개 출처 기록이며, KSI가 해당 자료를 내려받거나 검증하지 않습니다. 권리 허락이 아닙니다.</p>
          <div className="mt-2 grid gap-2">
            <label className="flex flex-col gap-1 font-semibold">공개 출처 주소<input className="input" aria-label="원본 공개 출처 주소" value={upstreamUri} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} inputMode="url" placeholder="https://" onChange={(event) => setUpstreamUri(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">원본 확인값 (선택)<input className="input" aria-label="원본 확인값" value={upstreamSha} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} placeholder="64자리 소문자 16진수" onChange={(event) => setUpstreamSha(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">발행자 표시 권리 안내 (선택)<input className="input" aria-label="발행자 표시 권리 안내" value={upstreamLicence} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setUpstreamLicence(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">가져온 과정 기록 (선택)<input className="input" aria-label="원본 가져온 과정 기록" value={upstreamNote} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setUpstreamNote(event.target.value)} /></label>
          </div>
        </details>
        <details className="rounded-lg border border-line bg-sunk p-3 text-[12px]">
          <summary className="tap-target cursor-pointer font-semibold">내보내기 도구 (선택)</summary>
          <p className="mt-1 leading-5 text-ink-2">원본을 만든 재구성 소프트웨어가 아니라, 등록할 GeoTIFF를 내보낸 도구를 적으세요. 모르면 비워 두세요.</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 font-semibold">도구 이름<input className="input" aria-label="내보내기 도구 이름" value={exportToolName} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setExportToolName(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">도구 버전<input className="input" aria-label="내보내기 도구 버전" value={exportToolVersion} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setExportToolVersion(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">내보내기 설정 확인값 (선택)<input className="input" aria-label="내보내기 설정 확인값" value={exportSettingsDigest} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} placeholder="sha256:…" onChange={(event) => setExportSettingsDigest(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">내보내기 시각 (선택)<input className="input" aria-label="내보내기 시각 (한국 표준시)" type="datetime-local" step="1" value={exportedAtLocal} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setExportedAtLocal(event.target.value)} /></label>
          </div>
          <label className="mt-2 flex flex-col gap-1 font-semibold">내보내기 기록 (선택)<input className="input" aria-label="내보내기 기록" value={exportNote} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setExportNote(event.target.value)} /></label>
        </details>
        <FilePickerField
          label="정사영상 (선택)"
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
          disabled={busy || hashing || Boolean(frozenAttempt) || (!newIntentAllowed && !resume)}
          onSelect={(file) => void select("dsm", file ?? undefined)}
          selectedFileName={dsm?.file.name ?? null}
        />
        <p className="text-[12px] leading-5 text-ink-2">정사영상 또는 DSM 중 하나 이상을 선택하세요. 원본 사진은 요청하지 않습니다.</p>
        {dsm && headers.dsm && <ExternalHeaderRecognition slot="dsm" state={headers.dsm} crs={declaredCrs.dsm} crsLocked={busy || hashing || formIsFrozen || !newIntentAllowed} resumingRegistered={Boolean(resume)} onCrsChange={(value) => setDeclaredCrs((current) => ({ ...current, dsm: value }))} />}
        <p className="text-[12px] leading-5 text-ink-2">파일 이름은 영문·숫자로 시작하고 영문·숫자·밑줄(_)·점(.)·하이픈(-)만 쓸 수 있습니다(최대 255자). 원본 파일은 바꾸지 말고 조건에 맞는 이름의 복사본을 선택하세요. 이름을 자동으로 바꾸지는 않습니다.</p>
        {(["ortho", "dsm"] as const).map((kind) => {
          const issue = nameIssues[kind];
          if (!issue) return null;
          const keptName = kind === "ortho" ? ortho?.file.name ?? null : dsm?.file.name ?? null;
          const slotLabel = kind === "ortho" ? "정사영상" : "DSM";
          return <div key={kind} role="alert" className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">
            <p className="break-all">‘{issue.fileName}’ 파일은 등록할 수 없습니다. {issue.reason} 원본 파일은 바꾸지 말고, 조건에 맞는 이름의 복사본을 선택하세요.</p>
            {keptName
              ? <p className="mt-1">이전에 확인한 {slotLabel} 파일({keptName})은 그대로 두었습니다. 유효한 파일을 다시 선택하면 바뀌고, 지우면 비워집니다.</p>
              : <p className="mt-1">선택된 {slotLabel} 파일이 없습니다. 조건에 맞는 복사본을 다시 선택하세요.</p>}
            <button className="btn mt-2 w-fit" disabled={busy || hashing || Boolean(frozenAttempt)} onClick={() => clearSlot(kind)}>이전 선택 지우기</button>
          </div>;
        })}
        {newIntentAllowed && (resume || frozenAttempt) && <button className="btn w-fit" disabled={busy || hashing} onClick={startNewAttempt}>새로 등록하기</button>}
        {hashing && <p role="status" className="text-ink-2">파일 확인 중: {formatBytesKo(hashProgress ?? 0)}</p>}
        {hashing && <button className="btn w-fit" onClick={cancelHash}>파일 확인 취소</button>}
        <p className="text-ink-2">{ortho ? `정사영상 ${formatFileSize(ortho.size)} 확인 완료` : dsm ? "정사영상 미선택" : "등록할 파일(정사영상 또는 DSM)을 선택하세요."}{dsm ? ` · DSM ${formatFileSize(dsm.size)} 확인 완료` : ortho ? " · DSM 미선택" : ""}</p>
        {hasFile && !formIsFrozen && metadataIssue !== null && <p role="status" className="text-ink-2">{metadataIssue}</p>}
        <button className="btn w-fit" disabled={!canSubmit} onClick={() => void submit()}>{busy ? "자료 등록 마무리 중" : sealedComplete ? "파일 제출 완료" : "자료 등록 마치기"}</button>
        <p className="text-[12px] leading-5 text-ink-2">마치면 파일 검사가 준비됩니다. 검증 완료를 뜻하지 않습니다. 등록은 검사·분석 승인이 아니며, 미상 정보가 있으면 이후 분석·비교 가능 여부는 별도로 확인합니다.</p>
        {uploadProgress && <p role="status" className="text-ink-2">{uploadProgress.artifactId === "ortho" ? "정사영상" : "DSM"} {uploadProgress.phase === "uploaded" ? "파일 전송 완료" : "파일 전송 중"}: {formatBytesKo(uploadProgress.transferredBytes)} / {formatBytesKo(uploadProgress.totalBytes)} {uploadProgress.phase === "uploading" && " · 전송 시간이나 비율은 추정하지 않습니다."}</p>}
        {busy && <button className="btn w-fit" onClick={cancelSubmission}>등록 중단</button>}
        {message && <p role="status" className="text-ink-2">{message}</p>}
      </div>
    </ResponsiveActionBoundary>}
      </div>
    </details>}
    {listState === "ready" && revisions.length > 0 && <ul className="flex flex-col gap-2 text-ink-2">{revisions.map((revision) => {
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
      const captureLine = describeCaptureLine(revision.submission.inputDeclaration as { captureBasis?: string | null; captureDate?: string | null; captureStartedAt?: string | null; captureEndedAt?: string | null } | null | undefined, (startedAt, endedAt) => `${formatKoreanDateTime(startedAt, { dateStyle: "short", timeStyle: "short" })} – ${formatKoreanDateTime(endedAt, { dateStyle: "short", timeStyle: "short" })}`);
      const producerLine = describeProducerLine(revision.submission.producerDeclaration);
      const retentionLine = describeRetentionLine(revision.submission.inputDeclaration);
      // V1/V2 기록의 행 표시는 그대로 둔다. 새 행 줄(제작·시점 선언)은 V3 표식이
      // 있을 때만 싣는다 — 실행 주체·장소 고정값(접수 정체성)을 재구성 실행
      // 사실처럼 읽히게 하지 않는다.
      const isV3Record = revision.submission.contractVersion === "external-reconstruction-submission.v3"
        || revision.submission.producerDeclaration?.producerKnowledge != null
        || revision.submission.inputDeclaration?.captureBasis != null;
      return <li key={key} className="rounded-lg border border-line px-3 py-2"><p>{describeArtifactKinds(revision.submission.artifacts)} · {formatRegistrationVersion(revision.submission.revision)} · {presentation?.title ?? (inspection?.phase === "error" ? "검사 상태를 불러오지 못했습니다." : "검사 상태 확인 중")}</p>
        {isV3Record && producerLine && <p className="mt-1 text-[12px] leading-5 text-ink-2">{producerLine}</p>}
        {isV3Record && captureLine && <p className="mt-1 text-[12px] leading-5 text-ink-2">{captureLine}</p>}
        {presentation && <><p className="mt-1 text-[12px] leading-5 text-ink-2">{presentation.detail}</p><p className="mt-1 text-[12px] leading-5 text-ink-muted">다음: {presentation.nextAction}</p>{presentation.artifactReasons.length > 0 && <ul className="mt-1 list-disc pl-5 text-[12px] leading-5 text-high-ink">{presentation.artifactReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}</>}
        {inspection?.phase === "loading" && inspectionView !== null && <p role="status" className="mt-1 text-[12px] text-ink-2">마지막으로 확인한 검사 상태를 유지한 채 업데이트를 확인하고 있습니다.</p>}
        {inspection?.phase === "error" && inspectionView !== null && <p role="alert" className="mt-1 text-[12px] text-high-ink">검사 상태 업데이트를 확인하지 못했습니다. 마지막으로 확인한 상태를 표시합니다. 새로고침으로 다시 시도하세요.</p>}
        {inspectionAutoRefreshStopped && presentation?.autoRefresh && <p role="status" className="mt-1 text-[12px] text-ink-2">자동 상태 확인을 멈췄습니다. 마지막으로 확인한 검사 상태를 표시합니다. 새로고침으로 다시 확인하세요.</p>}
        <div className="mt-2 flex flex-wrap gap-2"><button className="btn" onClick={() => { inspectionAutoRefreshBudget.current = 0; setInspectionAutoRefreshStopped(false); void loadInspection(revision); }}>검사 상태 새로고침</button>{display && <button className="btn" onClick={() => setVisibleDisplay((current) => current === key ? null : key)}>{visibleDisplay === key ? "표시용 정사영상 닫기" : "표시용 정사영상 열기"}</button>}{canWrite && revision.state === "REGISTERED" && <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" reason="등록 중인 외부 산출물을 다시 이어가는 일은 노트북 이상의 화면에서만 진행합니다."><button className="btn" onClick={() => selectResume(revision)}>등록 이어하기</button></ResponsiveActionBoundary>}</div>
        {display && visibleDisplay === key && <ExternalSanitizedOrthophoto workOrderId={workOrderId} submissionRef={revision.submissionRef} revision={revision.submission.revision} sanitizedDisplayRef={display.sanitizedDisplayRef} receiptDigest={display.receiptDigest} onDismiss={() => setVisibleDisplay(null)} />}
        <details className="mt-1 text-[12px] text-ink-2"><summary className="tap-target cursor-pointer">파일 정보 · 처리 상세</summary><div className="mt-1 break-all"><p>제출 상태: {submissionStateLabel(revision.state)} ({revision.state})</p><p>제출 식별자: {revision.submissionRef}</p>{producerLine && <p>{producerLine}</p>}{isV3Record && revision.submission.producerDeclaration?.sourceNote && <p>출처 기록: {revision.submission.producerDeclaration.sourceNote}</p>}{isV3Record && captureLine && <p>{captureLine}</p>}{isV3Record && retentionLine && <p>{retentionLine}</p>}{isV3Record && revision.submission.inputDeclaration?.upstreamSource && <><p>공개 출처 주소: {revision.submission.inputDeclaration.upstreamSource.sourceUri ?? "확인 필요"} (내려받거나 검증하지 않습니다)</p><p>공개 출처 확인값·권리·과정: {[revision.submission.inputDeclaration.upstreamSource.sourceSha256, revision.submission.inputDeclaration.upstreamSource.licenceDeclaration, revision.submission.inputDeclaration.upstreamSource.retrievalNote].filter((part) => typeof part === "string" && part.length > 0).join(" · ") || "신고 없음"}</p></>}{isV3Record && revision.submission.inputDeclaration?.derivativeExport && <p>내보내기 도구: {revision.submission.inputDeclaration.derivativeExport.toolName ?? "확인 필요"}{revision.submission.inputDeclaration.derivativeExport.toolVersion ? ` ${revision.submission.inputDeclaration.derivativeExport.toolVersion}` : ""} (재구성 소프트웨어와 다를 수 있음)</p>}{revision.submission.observationEpochId && <p>촬영 기록: {revision.submission.observationEpochId}</p>}{revision.submission.artifacts?.map((artifact) => <p key={artifact.artifactId}>산출물: {artifact.kind} · {artifact.fileName} · {artifact.declaredSizeBytes}바이트 · 확인값(해시) {artifact.declaredSha256}</p>)}{inspectionView !== null && <><p>검사 상태: {inspectionView.inspection.state}</p><p>표시 상태: {inspectionView.display.state}</p>{inspectionView.inspection.outcome?.map((outcome) => <p key={`${outcome.artifactId}:${outcome.outcome}:${outcome.reason ?? ""}`}>산출물 기록: {outcome.artifactId} · {outcome.outcome}{outcome.reason ? ` · 사유 코드/기록: ${outcome.reason}` : ""}</p>)}</>}</div></details>
      </li>;
    })}</ul>}
  </section>
  {/* 자식은 계속 마운트해 보존된 조회·시도 상태를 버리지 않는다. */}
  <details ref={legacyDetails} open={initialReport ? true : undefined} className="rounded-xl border border-line bg-sunk/40" aria-label="이전 비교 흐름 기록">
    <summary className="tap-target cursor-pointer px-4 py-3 text-[13px] font-bold text-ink-2">이전 비교 흐름(V1) · 검사점·물량·재관측</summary>
    <div className="flex flex-col gap-3 border-t border-line p-4">
      <p className="text-[12px] leading-5 text-ink-muted">이전 흐름의 기록 조회와 요청 기능입니다. 새 변화 분석과 결과 검토는 현장의 분석·검토에서 진행합니다.</p>
    <ExternalEvidencePanel workOrderId={workOrderId} siteId={siteId} revisions={revisions} canWrite={canWrite} newIntentAllowed={newIntentAllowed} onRelativeVolumeDecisionChange={receiveRelativeVolumeDecision} onSingleVolumeDecisionChange={receiveSingleVolumeDecision} />
    <ExternalResultWorkflowPanel workOrderId={workOrderId} siteId={siteId} decision={relativeVolumeDecision} singleVolumeDecision={singleVolumeDecision} initialReport={initialReport} permissions={permissions ?? (canWrite ? ["SITES_WRITE"] : [])} workAreaNames={workAreaNames} newIntentAllowed={newIntentAllowed} />
    </div>
  </details>
  </>;
}

export function ExternalReconstructionPanel(props: { workOrderId: string; siteId?: string; expectedEpochId: string | null; canWrite: boolean; permissions?: readonly string[]; initialReport?: TrustedExternalResultLink; requiresCaptureInterval?: boolean; newIntentAllowed?: boolean; workAreaNames?: Readonly<Record<string, string>> }) {
  return <ExternalReconstructionPanelState key={`${props.workOrderId}:${props.initialReport?.reportRef ?? ""}:${props.initialReport?.reportDigest ?? ""}`} {...props} />;
}
