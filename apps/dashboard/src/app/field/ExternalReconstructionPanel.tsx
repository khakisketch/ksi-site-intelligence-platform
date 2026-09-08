"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { putExternalReconstructionFile } from "@/lib/external-reconstruction-upload";
import type { ExternalArtifactKind } from "@/lib/external-reconstruction-submission";

type HashResult = { file: File; sha256: string; size: number };
type ArtifactDeclaration = { artifactId: ExternalArtifactKind; kind: ExternalArtifactKind; fileName: string; format: "GeoTIFF"; contentType: "application/octet-stream"; declaredSha256: string; declaredSizeBytes: number; declaredCrs: null; declaredVerticalReference: null; declaredGsdM: null };
type Revision = { submissionRef: string; submission: { submissionId?: string; revision: number; observationEpochId?: string; producerDeclaration?: { softwareName?: string; softwareVersion?: string }; submittedAt?: string; artifacts?: { artifactId: "ortho" | "dsm"; kind: "ortho" | "dsm"; fileName: string; declaredSha256: string; declaredSizeBytes: number }[] }; state: "REGISTERED" | "SEALED" };
type FrozenAttempt = { requestBody: Readonly<{ submissionId: string; expectedEpochId: string; submittedAt: string; softwareName: string; softwareVersion: string; artifacts: readonly ArtifactDeclaration[] }>; bindings: readonly HashResult[] };

function utcSeconds(): string { return new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); }
function attemptId(): string { return `console-${crypto.randomUUID()}`; }
function abortError(): DOMException { return new DOMException("Operation was aborted", "AbortError"); }
function isAbortError(error: unknown): boolean { return error instanceof DOMException && error.name === "AbortError"; }

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

function artifact(kind: ExternalArtifactKind, value: HashResult): ArtifactDeclaration {
  return { artifactId: kind, kind, fileName: value.file.name, format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: value.sha256, declaredSizeBytes: value.size, declaredCrs: null, declaredVerticalReference: null, declaredGsdM: null };
}

function exactBindingsMatch(expected: NonNullable<Revision["submission"]["artifacts"]>, actual: readonly ArtifactDeclaration[]): boolean {
  return expected.length === actual.length && expected.every((item) => {
    const selected = actual.find((candidate) => candidate.kind === item.kind);
    return selected !== undefined && selected.declaredSha256 === item.declaredSha256 && selected.declaredSizeBytes === item.declaredSizeBytes;
  });
}

function ExternalReconstructionPanelState({ workOrderId, expectedEpochId, canWrite }: { workOrderId: string; expectedEpochId: string | null; canWrite: boolean }) {
  const workers = useRef(new Set<Worker>());
  const scope = useRef(0);
  const listAbort = useRef<AbortController | null>(null);
  const hashAbort = useRef<AbortController | null>(null);
  const submissionAbort = useRef<AbortController | null>(null);
  const [submissionId, setSubmissionId] = useState(attemptId);
  const [submittedAt, setSubmittedAt] = useState(utcSeconds);
  const [hashing, setHashing] = useState(false);
  const [hashProgress, setHashProgress] = useState<number | null>(null);
  const [softwareName, setSoftwareName] = useState("");
  const [softwareVersion, setSoftwareVersion] = useState("");
  const [ortho, setOrtho] = useState<HashResult | null>(null);
  const [dsm, setDsm] = useState<HashResult | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [resume, setResume] = useState<Revision | null>(null);
  const [frozenAttempt, setFrozenAttempt] = useState<FrozenAttempt | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const currentScope = useCallback((value: number) => scope.current === value, []);
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
      setListState("ready");
    } catch (error) {
      if (isAbortError(error) || !currentScope(requestScope) || listAbort.current !== controller) return;
      setListState("error");
    } finally {
      if (listAbort.current === controller) listAbort.current = null;
    }
  }, [currentScope, workOrderId]);

  // The keyed parent below remounts for a new work order, so this effect owns one scope only.
  useEffect(() => {
    const requestScope = scope.current + 1;
    scope.current = requestScope;
    const workerSet = workers.current;
    void load(requestScope);
    return () => {
      if (!currentScope(requestScope)) return;
      scope.current += 1;
      listAbort.current?.abort();
      hashAbort.current?.abort();
      submissionAbort.current?.abort();
      listAbort.current = null;
      hashAbort.current = null;
      submissionAbort.current = null;
      workerSet.forEach((worker) => worker.terminate());
      workerSet.clear();
    };
  }, [currentScope, load]);

  const cancelHash = () => {
    const controller = hashAbort.current;
    if (!controller) return;
    hashAbort.current = null;
    controller.abort();
    setHashing(false);
    setHashProgress(null);
  };

  const select = async (kind: ExternalArtifactKind, file?: File) => {
    if (!file || hashing || frozenAttempt) return;
    const requestScope = scope.current;
    const controller = new AbortController();
    hashAbort.current?.abort();
    hashAbort.current = controller;
    setHashing(true);
    setHashProgress(0);
    try {
      const result = await hashFile(file, workers.current, setHashProgress, controller.signal);
      if (!currentScope(requestScope) || hashAbort.current !== controller) return;
      if (kind === "ortho") {
        if (ortho && (ortho.sha256 !== result.sha256 || ortho.size !== result.size)) {
          setSubmissionId(attemptId());
          setSubmittedAt(utcSeconds());
          setDsm(null);
        }
        setOrtho(result);
      } else {
        setDsm(result);
      }
      setMessage(null);
    } catch (error) {
      if (!isAbortError(error) && currentScope(requestScope) && hashAbort.current === controller) setMessage("파일 해시를 계산하지 못했습니다.");
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
    setMessage("등록된 선언과 같은 파일을 다시 선택하세요.");
  };

  const startNewAttempt = () => {
    if (busy || hashing) return;
    setResume(null);
    setFrozenAttempt(null);
    setSubmissionId(attemptId());
    setSubmittedAt(utcSeconds());
    setMessage(null);
  };

  const freezeCurrentAttempt = (): FrozenAttempt | null => {
    if (!ortho || !expectedEpochId || !softwareName.trim() || !softwareVersion.trim()) return null;
    const artifacts = Object.freeze([artifact("ortho", ortho), ...(dsm ? [artifact("dsm", dsm)] : [])]);
    const requestBody = Object.freeze({ submissionId, expectedEpochId, submittedAt, softwareName: softwareName.trim(), softwareVersion: softwareVersion.trim(), artifacts });
    return Object.freeze({ requestBody, bindings: Object.freeze([ortho, ...(dsm ? [dsm] : [])]) });
  };

  const submit = async () => {
    if (!ortho || hashing || busy) return;
    let revision = resume;
    let bindings: readonly HashResult[];
    let attempt = frozenAttempt;
    if (revision) {
      const selectedArtifacts = [artifact("ortho", ortho), ...(dsm ? [artifact("dsm", dsm)] : [])];
      const expectedArtifacts = revision.submission.artifacts ?? [];
      if (!exactBindingsMatch(expectedArtifacts, selectedArtifacts)) {
        setMessage("선택한 파일이 등록된 선언의 종류, 해시 또는 크기와 일치하지 않습니다.");
        return;
      }
      bindings = [ortho, ...(dsm ? [dsm] : [])];
    } else {
      attempt ??= freezeCurrentAttempt();
      if (!attempt) return;
      if (!frozenAttempt) setFrozenAttempt(attempt);
      bindings = attempt.bindings;
    }

    const requestScope = scope.current;
    const controller = new AbortController();
    submissionAbort.current = controller;
    setBusy(true);
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
      for (const value of bindings) {
        const grant = grants.find((item) => item.artifactId === (value === bindings[0] ? "ortho" : "dsm"));
        if (!grant) throw new Error("missing upload grant");
        await putExternalReconstructionFile(grant, value.file, controller.signal);
        if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      }
      const seal = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/seal`, { method: "POST", signal: controller.signal });
      if (!seal.ok) throw new Error("seal failed");
      if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      setMessage("바이트 관측을 Core에 요청했습니다. 파일 형식·품질 또는 측정 적합성은 아직 검증되지 않았습니다.");
      await load(requestScope);
    } catch (error) {
      if (!isAbortError(error) && currentScope(requestScope) && submissionAbort.current === controller) setMessage("선언 또는 바이트 봉인에 실패했습니다. 목록을 다시 확인하세요.");
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
    setMessage("전송을 취소했습니다.");
  };

  const canSubmit = Boolean(ortho) && !busy && !hashing && (Boolean(resume) || Boolean(frozenAttempt) || Boolean(expectedEpochId && softwareName.trim() && softwareVersion.trim()));
  const formIsFrozen = Boolean(frozenAttempt || resume);

  return <section className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 text-[13px]">
    <div><h2 className="text-[16px] font-bold">외부 재구성 산출물</h2><p className="text-ink-2">외부에서 만든 GeoTIFF를 선언하고 바이트 관측만 봉인합니다. 형식, 품질, 측정·보고 적합성은 확인하지 않습니다.</p></div>
    {canWrite && <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" reason="외부 산출물 선언·업로드·봉인은 노트북 이상의 화면에서만 진행합니다.">
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 font-semibold">재구성 소프트웨어 이름<input className="input" aria-label="재구성 소프트웨어 이름" value={softwareName} disabled={busy || hashing || formIsFrozen} onChange={(event) => setSoftwareName(event.target.value)} /></label>
        <label className="flex flex-col gap-1 font-semibold">재구성 소프트웨어 버전<input className="input" aria-label="재구성 소프트웨어 버전" value={softwareVersion} disabled={busy || hashing || formIsFrozen} onChange={(event) => setSoftwareVersion(event.target.value)} /></label>
        <label className="flex flex-col gap-1 font-semibold">정사영상 (필수)<input className="input" aria-label="정사영상 GeoTIFF" type="file" accept=".tif,.tiff" disabled={busy || hashing || Boolean(frozenAttempt)} onChange={(event) => void select("ortho", event.target.files?.[0])} /></label>
        <label className="flex flex-col gap-1 font-semibold">DSM (선택)<input className="input" aria-label="DSM GeoTIFF" type="file" accept=".tif,.tiff" disabled={busy || hashing || Boolean(frozenAttempt) || !ortho} onChange={(event) => void select("dsm", event.target.files?.[0])} /></label>
        {(resume || frozenAttempt) && <button className="btn w-fit" disabled={busy || hashing} onClick={startNewAttempt}>새 선언으로 전환</button>}
        {hashing && <p role="status" className="text-ink-2">파일 해시 계산 중: {hashProgress?.toLocaleString() ?? 0} bytes</p>}
        {hashing && <button className="btn w-fit" onClick={cancelHash}>해시 취소</button>}
        <p className="text-ink-2">{ortho ? `정사영상 ${ortho.size.toLocaleString()} bytes 해시 완료` : "정사영상을 선택하세요."}{dsm ? ` · DSM ${dsm.size.toLocaleString()} bytes 해시 완료` : ""}</p>
        <button className="btn w-fit" disabled={!canSubmit} onClick={() => void submit()}>{busy ? "전송 중" : "선언·업로드·봉인"}</button>
        {busy && <button className="btn w-fit" onClick={cancelSubmission}>전송 취소</button>}
        {message && <p role="status" className="text-ink-2">{message}</p>}
      </div>
    </ResponsiveActionBoundary>}
    {!canWrite && <p className="text-ink-2">조회 전용 계정입니다.</p>}
    {listState === "loading" && <p role="status" className="text-ink-2">선언 목록을 불러오는 중입니다.</p>}
    {listState === "error" && <div role="alert" className="flex flex-col items-start gap-2 text-ink-2"><p>선언 목록을 불러오지 못했습니다.</p><button className="btn w-fit" onClick={() => void load()}>목록 다시 시도</button></div>}
    {listState === "ready" && <ul className="text-ink-2">{revisions.length === 0 ? <li>등록된 외부 산출물이 없습니다.</li> : revisions.map((revision) => <li key={revision.submissionRef}><span>{revision.submission.artifacts?.map((item) => item.fileName).join(", ") || "외부 산출물"} · {revision.submission.producerDeclaration?.softwareName ?? "재구성 소프트웨어"} {revision.submission.producerDeclaration?.softwareVersion ?? ""} · {revision.state === "SEALED" ? "파일 저장 확인 · 형식·품질 검사 미완료" : "등록됨 · 파일 저장 미확인"}</span>{canWrite && revision.state === "REGISTERED" && <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" reason="등록된 외부 선언 재개는 노트북 이상의 화면에서만 진행합니다."><button className="btn ml-2" onClick={() => selectResume(revision)}>등록된 선언 재개</button></ResponsiveActionBoundary>}<details className="mt-1"><summary>전문가 정보</summary><p>{revision.state}</p></details></li>)}</ul>}
  </section>;
}

export function ExternalReconstructionPanel(props: { workOrderId: string; expectedEpochId: string | null; canWrite: boolean }) {
  return <ExternalReconstructionPanelState key={props.workOrderId} {...props} />;
}
