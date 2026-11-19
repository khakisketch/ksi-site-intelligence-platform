"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ConsolePage } from "@/components/nav/ConsolePage";
import { siteDataHref } from "@/components/nav/site-context";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { ExternalResultFolderPicker } from "@/components/site/ExternalResultFolderPicker";
import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";
import { isExternalArtifactInspectionView } from "@/lib/external-submission-echo";
import type { ExternalArtifactKind } from "@/lib/external-reconstruction-submission";
import { hashFile, type HashResult } from "@/lib/file-sha256";
import { areaRingOf, coverageOfArea } from "@/lib/geo/geotiff-footprint";
import { koreanCalendarDate } from "@/lib/observation-default-name";
import { formatBytesKo } from "@/lib/number-format";
import { captureWindowIssue } from "@/lib/site-upload-declaration";
import { uploadedArtifactHref } from "@/lib/uploaded-asset-locator";
import { assignCandidates, chipsOf, inspectCandidate, type ChipTone, type UploadCandidate } from "@/lib/site-upload-files";
import { UploadFlowError, UploadSession, type UploadFlowEvent, type UploadFlowInput, type UploadFlowResult, type UploadFlowStage } from "@/lib/site-upload-flow";

import { UploadCompletion } from "./UploadCompletion";
import { UploadMap, type MapFootprint } from "./UploadMap";

export type UploadWorkArea = { workAreaId: string; name: string; polygon: Record<string, unknown> | null };

export type UploadScreenDeps = {
  inspect: typeof inspectCandidate;
  hash: (file: File, signal: AbortSignal, onProgress: (bytes: number) => void) => Promise<HashResult>;
  createSession: (input: UploadFlowInput) => { run: (signal: AbortSignal, onEvent: (event: UploadFlowEvent) => void) => Promise<UploadFlowResult> };
  readInspection: (result: UploadFlowResult, signal?: AbortSignal) => Promise<ExternalArtifactInspectionView | null>;
};

const defaultDeps: UploadScreenDeps = {
  inspect: inspectCandidate,
  hash: (file, signal, onProgress) => hashFile(file, new Set<Worker>(), onProgress, signal),
  createSession: (input) => new UploadSession(input),
  readInspection: async ({ workOrderId, submissionRef, revision }, signal) => {
    const deadline = AbortSignal.timeout(15_000);
    const readSignal = signal ? AbortSignal.any([signal, deadline]) : deadline;
    const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(submissionRef)}/revisions/${revision}/inspection`, { cache: "no-store", signal: readSignal });
    if (!response.ok) return null;
    const payload: unknown = await response.json().catch(() => null);
    return isExternalArtifactInspectionView(payload) ? payload : null;
  },
};

const KIND_LABEL = { ortho: "정사영상", dsm: "DSM (높이)" } as const;
const STAGE_LABEL: Record<UploadFlowStage, string> = {
  workOrder: "등록 작업을 만들고 있습니다.",
  register: "자료 정보를 등록하고 있습니다.",
  upload: "파일을 보내고 있습니다.",
  seal: "전송한 파일을 확인하고 제출을 마무리하고 있습니다.",
};
const CHIP_CLASS: Record<ChipTone, string> = {
  ok: "bg-safe-bg text-safe-ink",
  warn: "bg-high-bg text-high-ink",
  block: "bg-crit-bg text-crit-ink",
};
type HashState = { progress: number; result: HashResult | null; failed: boolean };
type Phase = "select" | "uploading" | "done";

let candidateCounter = 0;

function Chip({ tone, label, detail, open, onToggle }: { tone: ChipTone; label: string; detail: string | null; open: boolean; onToggle: () => void }) {
  const base = `inline-flex items-center rounded-full px-2.5 py-0.5 text-caption font-semibold ${CHIP_CLASS[tone]}`;
  if (!detail) return <span className={base}>{label}</span>;
  return <button type="button" className={`${base} cursor-pointer`} aria-expanded={open} onClick={onToggle}>{label}</button>;
}

export function UploadScreen({ siteId, siteName, workAreas, initialWorkAreaId, accountIdentity, deps = defaultDeps }: {
  siteId: string;
  siteName: string;
  workAreas: readonly UploadWorkArea[];
  initialWorkAreaId: string | null;
  accountIdentity: { fingerprint: string } | null;
  deps?: UploadScreenDeps;
}) {
  const [areaId, setAreaId] = useState(() => workAreas.find((area) => area.workAreaId === initialWorkAreaId)?.workAreaId ?? workAreas[0]?.workAreaId ?? "");
  const area = workAreas.find((item) => item.workAreaId === areaId) ?? null;
  const [candidates, setCandidates] = useState<UploadCandidate[]>([]);
  const [folderLabel, setFolderLabel] = useState("");
  const [hashes, setHashes] = useState<Record<string, HashState>>({});
  const [date, setDate] = useState<string | null>(null);
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [touched, setTouched] = useState(false);
  const [phase, setPhase] = useState<Phase>("select");
  // 한 번 시작한 요청은 같은 내용으로만 다시 보내므로, 실패 뒤에도 입력을 잠가 화면과 요청이 어긋나지 않게 한다.
  const [frozen, setFrozen] = useState(false);
  const [stage, setStage] = useState<UploadFlowStage | null>(null);
  const [transferringKind, setTransferringKind] = useState<ExternalArtifactKind | null>(null);
  const [doneKinds, setDoneKinds] = useState<ExternalArtifactKind[]>([]);
  const [readingHeaders, setReadingHeaders] = useState(false);
  const [selectionError, setSelectionError] = useState(false);
  const [error, setError] = useState<Pick<UploadFlowError, "message" | "ambiguous" | "recoveryWorkOrderId" | "recoveryCode" | "retrySameRevision"> | null>(null);
  const [result, setResult] = useState<UploadFlowResult | null>(null);
  const [openChip, setOpenChip] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const sessionRef = useRef<ReturnType<UploadScreenDeps["createSession"]> | null>(null);
  const runAbort = useRef<AbortController | null>(null);
  const headerAbort = useRef<AbortController | null>(null);
  const hashAbort = useRef(new Map<string, AbortController>());
  const fileInput = useRef<HTMLInputElement | null>(null);
  const today = useMemo(() => koreanCalendarDate(new Date()), []);
  const effectiveDate = date ?? today;

  // 구역을 바꾸면 이미 읽은 범위로 구역과의 관계만 다시 계산한다(파일은 다시 읽지 않는다).
  const shown = useMemo(() => candidates.map((candidate) => ({
    ...candidate,
    coverage: candidate.footprint ? coverageOfArea(candidate.footprint, area?.polygon) : null,
  })), [candidates, area]);
  const assignment = useMemo(() => assignCandidates(shown), [shown]);
  const slots = ([["ortho", assignment.ortho], ["dsm", assignment.dsm]] as const);
  const assigned = slots.flatMap(([kind, candidate]) => (candidate ? [{ kind, candidate }] : []));

  useEffect(() => () => {
    runAbort.current?.abort();
    headerAbort.current?.abort();
    for (const controller of hashAbort.current.values()) controller.abort();
  }, []);

  // 칸에 들어간 파일만 해시한다. 올리기 버튼을 누르기 전에 미리 계산해 두면 기다림이 줄어든다.
  const assignedKey = assigned.map(({ candidate }) => candidate.id).join("|");
  useEffect(() => {
    for (const { candidate } of assigned) {
      if (hashAbort.current.has(candidate.id)) continue;
      const controller = new AbortController();
      hashAbort.current.set(candidate.id, controller);
      setHashes((current) => ({ ...current, [candidate.id]: { progress: 0, result: null, failed: false } }));
      deps.hash(candidate.file, controller.signal, (bytes) => {
        setHashes((current) => current[candidate.id] ? { ...current, [candidate.id]: { ...current[candidate.id]!, progress: bytes / Math.max(candidate.file.size, 1) } } : current);
      }).then((value) => {
        if (controller.signal.aborted) return;
        setHashes((current) => ({ ...current, [candidate.id]: { progress: 1, result: value, failed: false } }));
      }).catch((cause: unknown) => {
        if (controller.signal.aborted || (cause instanceof DOMException && cause.name === "AbortError")) return;
        setHashes((current) => ({ ...current, [candidate.id]: { progress: 0, result: null, failed: true } }));
      });
    }
    // 칸에서 빠진 파일의 해시는 멈춘다.
    for (const [id, controller] of hashAbort.current) {
      if (!assigned.some(({ candidate }) => candidate.id === id)) {
        controller.abort();
        hashAbort.current.delete(id);
        setHashes((current) => { const next = { ...current }; delete next[id]; return next; });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- assignedKey가 칸의 구성을 대표한다.
  }, [assignedKey, deps]);

  const addFiles = useCallback(async (files: { file: File; kind?: ExternalArtifactKind }[], sourceLabel = "") => {
    if (phase !== "select" || sessionRef.current || headerAbort.current || files.length === 0) return;
    const controller = new AbortController();
    headerAbort.current = controller;
    setReadingHeaders(true);
    setSelectionError(false);
    try {
      const next: UploadCandidate[] = [];
      for (const { file, kind } of files) {
        const candidate = await deps.inspect(file, `f${++candidateCounter}`, area?.polygon, { signal: controller.signal });
        if (controller.signal.aborted) return;
        next.push(kind ? { ...candidate, expectedKind: kind } : candidate);
      }
      setCandidates((current) => [...current, ...next]);
      setFolderLabel(sourceLabel);
    } catch {
      if (!controller.signal.aborted) setSelectionError(true);
    } finally {
      headerAbort.current = null;
      if (!controller.signal.aborted) setReadingHeaders(false);
    }
  }, [area, deps, phase]);

  const addManualFiles = (files: FileList | null) => void addFiles(Array.from(files ?? [], (file) => ({ file })));

  const removeCandidate = (id: string) => {
    hashAbort.current.get(id)?.abort();
    hashAbort.current.delete(id);
    setCandidates((current) => current.filter((candidate) => candidate.id !== id));
    setFolderLabel("");
  };

  const startedLocal = startTime ? `${effectiveDate}T${startTime}` : "";
  const endedLocal = endTime ? `${effectiveDate}T${endTime}` : "";
  const timeIssue = captureWindowIssue(startedLocal, endedLocal);
  const hashed = assigned.every(({ candidate }) => hashes[candidate.id]?.result);
  const hashing = assigned.some(({ candidate }) => { const state = hashes[candidate.id]; return !state || (!state.result && !state.failed); });
  const hashFailed = assigned.some(({ candidate }) => hashes[candidate.id]?.failed);
  const locked = phase !== "select" || frozen;
  const canStart = Boolean(accountIdentity) && area !== null && assigned.length > 0 && hashed && !readingHeaders &&
    timeIssue === null && phase === "select" && (error?.ambiguous !== false || Boolean(error?.retrySameRevision));

  const run = async () => {
    if (!canStart || !accountIdentity || !area || runAbort.current || headerAbort.current) return;
    setError(null);
    setPhase("uploading");
    const session = sessionRef.current ?? deps.createSession({
      siteId,
      workAreaId: area.workAreaId,
      workAreaName: area.name,
      continuity: accountIdentity.fingerprint,
      startedLocal,
      endedLocal,
      files: assigned.map(({ kind, candidate }) => {
        const hash = hashes[candidate.id]!.result!;
        return {
          kind, file: candidate.file, fileName: candidate.file.name, sha256: hash.sha256, size: hash.size,
          declaredCrs: candidate.recognition?.declaredCrs ?? null, producer: candidate.recognition?.producer ?? null,
        };
      }),
    });
    sessionRef.current = session;
    setFrozen(true);
    const controller = new AbortController();
    runAbort.current = controller;
    try {
      const finished = await session.run(controller.signal, (event) => {
        if (event.type === "stage") setStage(event.stage);
        if (event.type === "progress") {
          setTransferringKind(event.kind);
          if (event.transferredBytes === 0) setDoneKinds((current) => current.filter((kind) => kind !== event.kind));
        }
        if (event.type === "fileDone") {
          setDoneKinds((current) => current.includes(event.kind) ? current : [...current, event.kind]);
          setTransferringKind(null);
        }
      });
      setResult(finished);
      setPhase("done");
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(cause instanceof UploadFlowError ? cause : {
        message: "올리는 중 문제가 생겼습니다. 다시 시도하세요.", ambiguous: true, recoveryWorkOrderId: null, recoveryCode: null, retrySameRevision: false,
      });
      setPhase("select");
    } finally {
      runAbort.current = null;
      setTransferringKind(null);
    }
  };

  // 서버가 분명히 거부한 경우에만 처음부터 새로 시작한다. 불확실한 실패는 같은 요청을 이어서 다시 보낸다.
  const startOver = () => { sessionRef.current = null; setFrozen(false); setError(null); setDoneKinds([]); };

  useEffect(() => {
    if (phase !== "uploading") return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [phase]);

  const reset = () => {
    sessionRef.current = null;
    setFrozen(false);
    setCandidates([]); setFolderLabel(""); setHashes({}); setStartTime(""); setEndTime(""); setTouched(false);
    setError(null); setResult(null); setSelectionError(false); setDoneKinds([]); setStage(null); setPhase("select");
  };

  const areaRing = area ? areaRingOf(area.polygon) : null;
  const footprints: MapFootprint[] = assigned.flatMap(({ kind, candidate }) => candidate.footprint ? [{ key: kind, label: KIND_LABEL[kind], ring: candidate.footprint.ring }] : []);
  const unmappedFiles = assigned.filter(({ candidate }) => !candidate.footprint).map(({ kind }) => KIND_LABEL[kind]);
  const uploadMap = <UploadMap area={areaRing} areaName={area?.name ?? ""} footprints={footprints} unmappedFiles={unmappedFiles} />;
  const returnHref = `/sites/${encodeURIComponent(siteId)}${area ? `?workAreaId=${encodeURIComponent(area.workAreaId)}` : ""}`;
  // 방금 올린 자료의 상세로 연다. DSM을 올렸으면 DSM(높이 기준 선택이 거기 있다), 아니면 정사영상.
  const openHref = result && area ? uploadedArtifactHref(siteId, {
    ...result, workAreaId: area.workAreaId, artifactId: assignment.dsm ? "dsm" : "ortho",
  }) : siteDataHref(siteId, { workAreaId: area?.workAreaId });

  return (
    <ConsolePage density="dense" className="!max-w-[1180px]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="console-page-title">자료 올리기 <span className="ml-2 text-body font-normal text-ink-muted">{siteName}</span></h2>
        <Link href={returnHref} className="text-body font-semibold text-ink-1 hover:underline">현장으로 돌아가기</Link>
      </div>

      {workAreas.length === 0 ? (
        <section className="rounded-xl border border-line bg-surface p-5">
          <h3 className="text-lead font-bold">먼저 작업구역을 등록하세요</h3>
          <Link href={`/sites/${encodeURIComponent(siteId)}/work-areas`} className="btn mt-3">작업구역 보기</Link>
        </section>
      ) : result ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="relative hidden min-h-[520px] lg:block">
            {uploadMap}
          </div>
          <UploadCompletion result={result} readInspection={deps.readInspection}
            hasDsm={!!assignment.dsm} hasOrtho={!!assignment.ortho}
            assetHref={openHref} mapHref={returnHref} onReset={reset} />
        </div>
      ) : (
        <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" title="화면 폭 1024px 이상에서 올리기" reason="큰 파일은 노트북에서 같은 계정으로 올리세요. 이 화면은 화면 폭 1024px 이상에서 사용할 수 있습니다.">
          {workAreas.length > 1 && (
            <div role="group" aria-label="작업구역" className="flex flex-wrap gap-2">
              {workAreas.map((item) => (
                <button key={item.workAreaId} type="button" aria-pressed={item.workAreaId === areaId} disabled={locked} onClick={() => setAreaId(item.workAreaId)}
                  className={`tap-target rounded-full border px-3 py-1 text-body ${item.workAreaId === areaId ? "border-ink-1 bg-ink-1 text-surface" : "border-line-strong bg-surface text-ink-1"}`}>{item.name}</button>
              ))}
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div
              className={`relative min-h-[520px] rounded-xl ${dragging ? "ring-2 ring-ink-1" : ""}`}
              onDragOver={(event) => { event.preventDefault(); if (!locked && !readingHeaders) setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => { event.preventDefault(); setDragging(false); addManualFiles(event.dataTransfer.files); }}
            >
              {uploadMap}
              {assigned.length === 0 && (
                <div className="absolute inset-4 grid place-items-center overflow-y-auto rounded-xl border-2 border-dashed border-line-strong bg-surface/80 text-center">
                  <div className="flex w-full max-w-[440px] flex-col items-center gap-3 p-4">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M12 16V4m0 0-4 4m4-4 4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg>
                    <p className="text-lead font-bold">정사영상·DSM을 여기에 놓기</p>
                    <div className="flex w-full flex-wrap items-start justify-center gap-2">
                      <button type="button" className="btn" disabled={locked || readingHeaders} onClick={() => fileInput.current?.click()}>파일 고르기</button>
                      {candidates.length === 0 && <ExternalResultFolderPicker disabled={locked || readingHeaders}
                        onSelect={addFiles} />}
                    </div>
                    <p className="text-caption text-ink-muted">DJI Terra · PIX4Dmapper 결과 폴더 또는 개별 GeoTIFF<br />파일당 최대 2 GiB 검사 가능</p>
                  </div>
                </div>
              )}
              <input ref={fileInput} type="file" accept=".tif,.tiff" multiple hidden disabled={locked || readingHeaders} aria-label="자료 파일 고르기"
                onChange={(event) => { addManualFiles(event.target.files); event.target.value = ""; }} />
            </div>

            <div className="flex flex-col gap-3">
              {folderLabel && <p className="px-1 text-caption text-ink-2 [overflow-wrap:anywhere]" role="status">선택한 결과 폴더 · {folderLabel}</p>}
              {slots.map(([kind, candidate]) => {
                const hash = candidate ? hashes[candidate.id] : undefined;
                const hashPending = Boolean(hash && !hash.result && !hash.failed);
                const chips = candidate ? chipsOf(candidate) : [];
                return (
                  <section key={kind} aria-label={KIND_LABEL[kind]} className={`rounded-xl border bg-surface p-3 ${candidate ? "border-line" : "border-dashed border-line"}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-bold">{KIND_LABEL[kind]}</p>
                        <p className="truncate text-caption text-ink-muted">{candidate ? `${candidate.file.name} · ${formatBytesKo(candidate.file.size)}` : "아직 없음"}</p>
                      </div>
                      {candidate && !locked && <button type="button" className="tap-target text-caption text-ink-2 underline" aria-label={`${KIND_LABEL[kind]} ${hashPending ? "확인 취소" : "파일 빼기"}`} onClick={() => removeCandidate(candidate.id)}>{hashPending ? "확인 취소" : "빼기"}</button>}
                      {!candidate && !locked && assigned.length > 0 && <button type="button" className="btn" disabled={readingHeaders} onClick={() => fileInput.current?.click()}>파일 추가</button>}
                    </div>
                    {candidate && (
                      <>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {chips.map((chip) => <Chip key={chip.key} tone={chip.tone} label={chip.label} detail={chip.detail} open={openChip === `${candidate.id}:${chip.key}`} onToggle={() => setOpenChip((current) => current === `${candidate.id}:${chip.key}` ? null : `${candidate.id}:${chip.key}`)} />)}
                          {phase === "uploading" && <Chip tone={doneKinds.includes(kind) ? "ok" : "warn"} label={doneKinds.includes(kind) ? "전송 완료" : transferringKind === kind ? "전송 중" : "전송 대기"} detail={null} open={false} onToggle={() => undefined} />}
                        </div>
                        {chips.map((chip) => openChip === `${candidate.id}:${chip.key}` && chip.detail ? <p key={chip.key} className="mt-2 whitespace-pre-line rounded-lg bg-sunk px-3 py-2 text-caption text-ink-2">{chip.detail}</p> : null)}
                        {hash && !hash.result && !hash.failed && <div className="mt-2" role="progressbar" aria-label={`${KIND_LABEL[kind]} 확인 중`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(hash.progress * 100)}><div className="h-1.5 overflow-hidden rounded-full bg-sunk"><div className="h-full bg-ink-1" style={{ width: `${Math.round(hash.progress * 100)}%` }} /></div><p className="mt-1 text-caption text-ink-muted">파일 확인 중 {Math.round(hash.progress * 100)}%</p></div>}
                        {hash?.failed && <p role="alert" className="mt-2 text-caption text-high-ink">파일을 읽지 못했습니다. 다시 놓아 주세요.</p>}
                      </>
                    )}
                  </section>
                );
              })}
              {assignment.skipped.map((item) => (
                <section key={item.id} className="rounded-xl border border-high bg-surface p-3">
                  <div className="flex items-start justify-between gap-2"><p className="min-w-0 truncate font-bold">{item.name}</p>{!locked && <button type="button" className="tap-target text-caption text-ink-2 underline" onClick={() => removeCandidate(item.id)}>빼기</button>}</div>
                  <p className="mt-1 text-caption text-high-ink">{item.reason}</p>
                </section>
              ))}

              <fieldset className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-3" disabled={locked}>
                <legend className="px-1 text-caption text-ink-muted">촬영 (한국 표준시)</legend>
                <input type="date" aria-label="촬영 날짜" className="input" value={effectiveDate} suppressHydrationWarning onChange={(event) => { setDate(event.target.value); setTouched(true); }} />
                <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
                  <input type="time" aria-label="촬영 시작 시각" className="input" value={startTime} onChange={(event) => { setStartTime(event.target.value); setTouched(true); }} />
                  <span aria-hidden>~</span>
                  <input type="time" aria-label="촬영 종료 시각" className="input" value={endTime} onChange={(event) => { setEndTime(event.target.value); setTouched(true); }} />
                </div>
                {touched && timeIssue && <p role="alert" className="text-caption text-high-ink">{timeIssue}</p>}
                {!locked && area && <Link className="w-fit text-caption underline text-ink-2" href={`/sites/${encodeURIComponent(siteId)}/observations/new?workAreaId=${encodeURIComponent(area.workAreaId)}`}>촬영 시각을 모르면 상세 등록</Link>}
              </fieldset>

              {error && (
                <div role="alert" className="rounded-xl bg-high-bg px-3 py-2 text-body text-high-ink">
                  <p>{error.message}</p>
                  {!error.ambiguous && (
                    <div className="mt-1 flex flex-wrap gap-x-4">
                      {error.recoveryWorkOrderId && <Link prefetch={false} className="tap-target underline" href={`/field/work-orders/${encodeURIComponent(error.recoveryWorkOrderId)}`}>기존 등록 작업 열기</Link>}
                      {!error.retrySameRevision && <button type="button" className="tap-target underline" onClick={startOver}>처음부터 새로 시작</button>}
                    </div>
                  )}
                </div>
              )}
              {!accountIdentity && <p role="alert" className="text-body text-high-ink">계정을 확인하지 못해 올릴 수 없습니다. 로그인 상태를 확인한 뒤 화면을 다시 여세요.</p>}
              {selectionError && <p role="alert" className="text-caption text-high-ink">선택한 파일을 추가하지 못했습니다. 파일을 다시 고르세요.</p>}
              {hashFailed && <p role="alert" className="text-caption text-high-ink">파일을 읽지 못한 칸이 있습니다. 빼고 다시 놓아 주세요.</p>}
              <button type="button" className="btn btn-primary !min-h-[52px] text-lead" disabled={!canStart} onClick={() => void run()}>
                {phase === "uploading" ? "올리는 중…" : error?.retrySameRevision ? "같은 등록 다시 전송" : error?.ambiguous ? "같은 요청으로 다시 시도" : readingHeaders || (hashing && assigned.length > 0) ? "파일 확인 중…" : "올리기"}
              </button>
              {readingHeaders && <p role="status" className="text-caption text-ink-2">선택한 파일의 종류와 지도 범위를 확인하고 있습니다.</p>}
              {phase === "uploading" && stage && <p role="status" className="text-caption text-ink-2">{STAGE_LABEL[stage]} 이 창을 열어 두세요.</p>}
            </div>
          </div>
        </ResponsiveActionBoundary>
      )}
    </ConsolePage>
  );
}
