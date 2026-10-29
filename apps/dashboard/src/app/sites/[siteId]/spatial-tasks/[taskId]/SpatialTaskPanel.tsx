"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { WorkAreaChoiceMap } from "@/components/map/WorkAreaChoiceMap";
import { AnalysisCoverage } from "@/components/analysis/AnalysisCoverage";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { getAnalysisIssueGuidance } from "@/lib/analysis-guidance";
import type { AnalysisView } from "@/lib/core-api/analysis";
import type { WorkArea } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatCountKo, formatNumberKo, formatSignificantKo } from "@/lib/number-format";
import { isTaskView, selectorKey, spatialTaskError, TASK_PURPOSE_LABEL,
  type SpatialTaskOptions, type SpatialTaskPurpose, type SpatialTaskView } from "@/lib/spatial-task";

/**
 * Core 적합성 상태별 정직한 안내. 수치(result)는 계약상 COMPLETED +
 * PROVISIONAL_ACCURACY_UNVERIFIED/EVALUATED에서만 오므로, 나머지 문구는
 * 수치 없는 보류 상태·방어 분기에만 닿는다. 어떤 상태도 정확도·측량·정산
 * 적합성을 주장하지 않는다.
 */
function suitabilityNote(state: AnalysisView["suitabilityState"]): string {
  switch (state) {
    case "EVALUATED":
      return "독립 평가 근거가 있습니다. 이 기록은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다.";
    case "PROVISIONAL_ACCURACY_UNVERIFIED":
      return "독립 정확도 평가는 아직 확인되지 않았습니다. 이 기록은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다.";
    case "REASSESSMENT_REQUIRED":
      return "현장 적합성 재평가가 필요합니다. 재평가 전에는 이 기록을 물량 정확도 보증, 측량 승인 또는 정산 사용 근거로 사용하지 마세요.";
    case "REMEDIATION_REQUIRED":
      return "보완이 필요합니다. 보완 전에는 이 기록을 물량 정확도 보증, 측량 승인 또는 정산 사용 근거로 사용하지 마세요.";
    case "BLOCKED":
      return "차단된 분석입니다. 아래 사유와 보완 방법을 확인하기 전에는 이 기록의 어떤 수치도 사용하지 마세요.";
    default:
      return "적합성 상태를 확인할 수 없습니다. 원인을 확인하기 전에는 이 기록을 정확도·측량·정산 근거로 사용하지 마세요.";
  }
}

export function SpatialTaskPanel({ initialView, initialOptions, siteName, areas, canWrite }: {
  initialView: SpatialTaskView; initialOptions: SpatialTaskOptions; siteName: string; areas: WorkArea[]; canWrite: boolean;
}) {
  const [view, setView] = useState(initialView);
  const [options, setOptions] = useState(initialOptions);
  const [purpose, setPurpose] = useState(initialView.task.selection.purpose);
  const [areaId, setAreaId] = useState(initialView.task.selection.workAreaId ?? "");
  const [baselineKey, setBaselineKey] = useState(initialView.task.selection.inputs ? selectorKey(initialView.task.selection.inputs.baseline) : "");
  const [currentKey, setCurrentKey] = useState(initialView.task.selection.inputs ? selectorKey(initialView.task.selection.inputs.current) : "");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [accessLost, setAccessLost] = useState(false);
  const [followPaused, setFollowPaused] = useState(false);
  const [followGeneration, setFollowGeneration] = useState(0);
  const [confirmReload, setConfirmReload] = useState(false);
  const [serverStale, setServerStale] = useState(false);
  const [resumeBusy, setResumeBusy] = useState(false);
  const [resumeFailed, setResumeFailed] = useState(false);
  const mirrorRef = useRef({
    view: initialView,
    purpose: initialView.task.selection.purpose,
    areaId: initialView.task.selection.workAreaId ?? "",
    baselineKey: initialView.task.selection.inputs ? selectorKey(initialView.task.selection.inputs.baseline) : "",
    currentKey: initialView.task.selection.inputs ? selectorKey(initialView.task.selection.inputs.current) : "",
    busy: null as string | null,
    followPaused: false,
  });
  const viewGenRef = useRef(0);
  const checkRef = useRef<(reason: "visible" | "focus" | "manual") => void>(() => {});
  const trackView = (next: SpatialTaskView) => {
    mirrorRef.current = { ...mirrorRef.current, view: next };
    viewGenRef.current += 1;
    setView(next);
  };
  const trackBusy = (next: string | null) => {
    mirrorRef.current = { ...mirrorRef.current, busy: next };
    setBusy(next);
  };
  const trackDraft = (next: { purpose: SpatialTaskPurpose; areaId: string; baselineKey: string; currentKey: string }) => {
    mirrorRef.current = { ...mirrorRef.current, ...next };
    setPurpose(next.purpose);
    setAreaId(next.areaId);
    setBaselineKey(next.baselineKey);
    setCurrentKey(next.currentKey);
  };
  const trackFollowPaused = (next: boolean) => {
    mirrorRef.current = { ...mirrorRef.current, followPaused: next };
    setFollowPaused(next);
  };
  const { siteId, taskId } = view.task;
  const api = `/api/sites/${encodeURIComponent(siteId)}/spatial-tasks/${encodeURIComponent(taskId)}`;
  const selectedArea = areas.find((area) => area.workAreaId === areaId);
  const candidates = options.observations.filter((item) => item.workAreaIds.includes(areaId))
    .sort((a, b) => Date.parse(a.captureStartedAt) - Date.parse(b.captureStartedAt)
      || selectorKey(a.selector).localeCompare(selectorKey(b.selector)));
  const baseline = candidates.find((item) => selectorKey(item.selector) === baselineKey);
  const current = candidates.find((item) => selectorKey(item.selector) === currentKey);
  const dirty = purpose !== view.task.selection.purpose || (areaId || null) !== view.task.selection.workAreaId
    || baselineKey !== (view.task.selection.inputs ? selectorKey(view.task.selection.inputs.baseline) : "")
    || currentKey !== (view.task.selection.inputs ? selectorKey(view.task.selection.inputs.current) : "");
  const locked = view.task.executionRequested;
  const supported = purpose === "OBSERVED_CHANGE";
  const complete = supported && Boolean(areaId && baseline && current && baselineKey !== currentKey);
  const canAct = canWrite && !busy;
  const pending = view.analysis?.executionState === "QUEUED" || view.analysis?.executionState === "RUNNING";
  const saveHintId = "task-save-hint";
  const saveHint = !dirty && !locked && canWrite && !complete
    ? purpose === "CLARIFY" ? "무엇을 확인할지 먼저 선택하세요."
    : !areaId ? "어느 구역인지 선택하면 ‘이 선택으로 계속’을 누를 수 있습니다."
    : !supported ? null
    : "서로 다른 이전·이후 관측을 선택하면 저장할 수 있습니다."
    : null;
  const linkedAnalysisId = view.task.analysisId;
  const savedSelectionKey = JSON.stringify(view.task.selection);

  useEffect(() => {
    if (!pending || !linkedAnalysisId || accessLost) return;
    let active = true, attempts = 0, failures = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let requestController: AbortController | null = null;
    const schedule = () => { if (active) timer = setTimeout(() => { void follow(); }, 3000); };
    const follow = async () => {
      if (!active) return;
      if (document.visibilityState === "hidden") { schedule(); return; }
      if (++attempts > 120) {
        trackFollowPaused(true);
        setError("분석 진행 상태의 자동 확인을 잠시 멈췄습니다. 계산 실패를 뜻하지 않습니다. 진행 상태를 다시 확인하세요.");
        return;
      }
      const controller = new AbortController(); requestController = controller;
      const deadline = setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch(api, { method: "GET", cache: "no-store", signal: controller.signal });
        if (!active) return;
        if (controller.signal.aborted) throw new Error("Task read timed out");
        if ([401,403,404,410].includes(response.status)) {
          setError(spatialTaskError(undefined, response.status)); setAccessLost(true); return;
        }
        const value: unknown = await response.json();
        if (!active) return;
        if (controller.signal.aborted) throw new Error("Task read timed out");
        if (!response.ok || !isTaskView(value, siteId, taskId) || value.task.analysisId !== linkedAnalysisId
          || JSON.stringify(value.task.selection) !== savedSelectionKey) throw new Error("Unexpected task response");
        failures = 0;
        trackView(value); setError(""); setResumeFailed(false);
        const state = value.analysis?.executionState;
        if (state === "COMPLETED") { setNotice("분석이 완료되었습니다. 같은 작업의 결과와 근거를 아래에서 확인하세요."); return; }
        if (state === "FAILED" || state === "NOT_STARTED" || value.state === "SELECTION_UNAVAILABLE") {
          setNotice("분석 진행 상태가 바뀌었습니다. 아래 사유와 보완 방법을 확인하세요."); return;
        }
        schedule();
      } catch {
        if (!active) return;
        if (++failures >= 3) {
          trackFollowPaused(true);
          setError("진행 상태를 확인하지 못해 자동 확인을 멈췄습니다. 계산 실패를 뜻하지 않습니다. 연결을 확인하고 다시 확인하세요.");
        } else {
          setError("진행 상태를 일시적으로 확인하지 못했습니다. 같은 작업을 다시 확인하고 있습니다.");
          schedule();
        }
      } finally { clearTimeout(deadline); }
    };
    schedule();
    return () => { active = false; if (timer) clearTimeout(timer); requestController?.abort(); };
  }, [accessLost, api, followGeneration, linkedAnalysisId, pending, savedSelectionKey, siteId, taskId]);

  useEffect(() => {
    mirrorRef.current = { ...mirrorRef.current, busy, followPaused };
  }, [busy, followPaused]);

  useEffect(() => {
    if (accessLost) return;
    let active = true;
    let inFlight = false;
    let requestController: AbortController | null = null;
    const sameCurrent = (a: SpatialTaskView, b: SpatialTaskView) =>
      a.task.revision === b.task.revision
      && JSON.stringify(a.task.selection) === JSON.stringify(b.task.selection)
      && a.task.analysisId === b.task.analysisId && a.state === b.state
      && JSON.stringify(a.analysis) === JSON.stringify(b.analysis)
      && JSON.stringify(a.readiness) === JSON.stringify(b.readiness);
    const viewMirrorStale = (issued: SpatialTaskView) => mirrorRef.current.view !== issued;
    const markFailed = (controller: AbortController) => {
      if (active && requestController === controller) setResumeFailed(true);
    };
    const check = async (reason: "visible" | "focus" | "manual") => {
      if (!active || inFlight) return;
      if (document.visibilityState === "hidden" && reason !== "manual") return;
      const mirror = mirrorRef.current;
      if (mirror.busy || accessLost) return;
      const mirrorPending = mirror.view.analysis?.executionState === "QUEUED"
        || mirror.view.analysis?.executionState === "RUNNING";
      if (reason !== "manual" && mirrorPending && !mirror.followPaused) return;
      const issuedView = mirror.view;
      const issuedGen = viewGenRef.current;
      inFlight = true;
      setResumeBusy(true);
      requestController?.abort();
      const controller = new AbortController();
      requestController = controller;
      const deadline = setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch(api, { method: "GET", cache: "no-store", signal: controller.signal });
        if (!active) return;
        if (controller.signal.aborted) { markFailed(controller); return; }
        if ([401, 403, 404, 410].includes(response.status)) {
          setError(spatialTaskError(undefined, response.status));
          setAccessLost(true);
          return;
        }
        const value: unknown = await response.json().catch(() => null);
        if (!active) return;
        if (controller.signal.aborted) { markFailed(controller); return; }
        if (requestController !== controller) return;
        if (!response.ok || !isTaskView(value, siteId, taskId)) { markFailed(controller); return; }
        if (mirrorRef.current.busy) return;
        if (viewGenRef.current !== issuedGen) return;
        if (viewMirrorStale(issuedView)) return;
        const curView = mirrorRef.current.view;
        if (value.task.revision < curView.task.revision) return;
        const draft = mirrorRef.current;
        const dirtyNow = draft.purpose !== curView.task.selection.purpose
          || (draft.areaId || null) !== curView.task.selection.workAreaId
          || draft.baselineKey !== (curView.task.selection.inputs ? selectorKey(curView.task.selection.inputs.baseline) : "")
          || draft.currentKey !== (curView.task.selection.inputs ? selectorKey(curView.task.selection.inputs.current) : "");
        if (sameCurrent(value, curView)) {
          setServerStale(false);
          setResumeFailed(false);
          return;
        }
        if (dirtyNow) {
          setServerStale(true);
          setResumeFailed(false);
          return;
        }
        const previousExecution = curView.analysis?.executionState;
        trackView(value);
        trackDraft({ purpose: value.task.selection.purpose, areaId: value.task.selection.workAreaId ?? "",
          baselineKey: value.task.selection.inputs ? selectorKey(value.task.selection.inputs.baseline) : "",
          currentKey: value.task.selection.inputs ? selectorKey(value.task.selection.inputs.current) : "" });
        setServerStale(false);
        trackFollowPaused(false);
        setResumeFailed(false);
        setError("");
        const nextExecution = value.analysis?.executionState;
        if (nextExecution === "COMPLETED" && previousExecution !== "COMPLETED") {
          setNotice("분석이 완료되었습니다. 같은 작업의 결과와 근거를 아래에서 확인하세요.");
        } else if (value.state === "SELECTION_UNAVAILABLE") {
          setNotice("저장된 구역이나 자료를 지금 사용할 수 없습니다. 사용 가능한 후보로 바꾸거나 담당자에게 권한을 확인하세요.");
        } else if (nextExecution === "FAILED" || nextExecution === "NOT_STARTED") {
          setNotice("분석 진행 상태가 바뀌었습니다. 아래 사유와 보완 방법을 확인하세요.");
        } else {
          setNotice("같은 작업의 최신 상태를 불러왔습니다. 결과와 근거를 아래에서 확인하세요.");
        }
        void reason;
      } catch {
        if (!active) return;
        if (controller.signal.aborted && requestController !== controller) return;
        markFailed(controller);
      } finally {
        clearTimeout(deadline);
        if (active) { inFlight = false; setResumeBusy(false); }
      }
    };
    checkRef.current = check;
    const onVisible = () => { if (document.visibilityState === "visible") void check("visible"); };
    const onFocus = () => { void check("focus"); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onFocus);
    return () => {
      active = false;
      requestController?.abort();
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onFocus);
    };
  }, [accessLost, api, siteId, taskId]);

  const setDraftFields = (next: { purpose?: SpatialTaskPurpose; areaId?: string; baselineKey?: string; currentKey?: string }) => {
    const base = mirrorRef.current;
    const merged = {
      purpose: next.purpose ?? base.purpose,
      areaId: next.areaId ?? base.areaId,
      baselineKey: next.baselineKey ?? base.baselineKey,
      currentKey: next.currentKey ?? base.currentKey,
    };
    mirrorRef.current = { ...mirrorRef.current, ...merged };
    if (next.purpose !== undefined) setPurpose(next.purpose);
    if (next.areaId !== undefined) setAreaId(next.areaId);
    if (next.baselineKey !== undefined) setBaselineKey(next.baselineKey);
    if (next.currentKey !== undefined) setCurrentKey(next.currentKey);
  };

  async function request(action: "selection" | "readiness" | "run" | "refresh") {
    if (action === "refresh") { window.location.reload(); return; }
    if (action === "selection" && purpose === "CLARIFY") {
      setError("무엇을 확인할지 먼저 선택하세요."); document.getElementById("task-purpose")?.focus(); return;
    }
    if (action === "selection" && Boolean(baselineKey || currentKey) && (!baseline || !current || baselineKey === currentKey)) {
      setError("서로 다른 이전·이후 관측을 함께 선택하세요. 구역만 저장하려면 두 관측 선택을 모두 비우세요.");
      document.getElementById(!baseline ? "task-baseline" : "task-current")?.focus(); return;
    }
    trackBusy(action); setError(""); setNotice("");
    try {
      const body = action === "selection" ? {
        expectedRevision: mirrorRef.current.view.task.revision, purpose, workAreaId: areaId || null,
        inputs: baseline && current && baselineKey !== currentKey ? { baseline: baseline.selector, current: current.selector } : null,
      } : { expectedRevision: view.task.revision };
      const response = await fetch(`${api}/${action}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body), cache: "no-store",
      });
      const value = await response.json();
      if (!response.ok) { setError(spatialTaskError(value.code, response.status)); return; }
      if (!isTaskView(value, siteId, taskId)) throw new Error("Invalid task response");
      trackView(value);
      setServerStale(false);
      setResumeFailed(false);
      if (action === "selection") setNotice("선택을 저장했습니다. 외부 대화에서 ‘선택했어’라고 하면 같은 작업을 이어갈 수 있습니다.");
      if (action === "run") setNotice("Core의 분석 기록에 연결했습니다. 결과와 근거는 아래에서 확인하세요.");
    } catch { setError("연결을 확인하지 못했습니다. 입력은 유지됩니다. 새로 불러와 저장 여부를 확인하세요."); }
    finally { trackBusy(null); }
  }

  async function more() {
    if (options.nextOffset === null) return;
    trackBusy("more"); setError("");
    try {
      const response = await fetch(`${api}/options?offset=${options.nextOffset}`, { cache: "no-store" });
      const value: SpatialTaskOptions & { code?: string } = await response.json();
      if (!response.ok) { setError(spatialTaskError(value.code, response.status)); return; }
      if (value.siteId !== siteId || !Array.isArray(value.observations)) throw new Error("Invalid options");
      setOptions((old) => ({ ...value, observations: [...old.observations, ...value.observations] }));
    } catch { setError("관측 목록을 불러오지 못했습니다. 다시 시도하세요."); }
    finally { trackBusy(null); }
  }

  const issues = dirty ? [] : view.readiness?.blockers ?? view.analysis?.blockers ?? [];
  const result = dirty ? null : view.analysis?.result;
  const shownNumber = (value: number) => Math.abs(value) > 0 && Math.abs(value) < 0.1
    ? formatSignificantKo(value, 3) : formatNumberKo(value, 1);
  if (accessLost) return <div className="mx-auto max-w-5xl p-5">
    <h1 className="text-xl font-bold">작업을 다시 확인하세요</h1>
    <p role="alert" className="mt-3 text-sm leading-6 text-high-ink">{error}</p>
    <p className="mt-2 text-sm leading-6 text-ink-2">이 화면의 구역·자료·결과는 더 이상 표시하지 않습니다. 기존 분석 기록을 삭제하거나 새 계산을 요청하지는 않았습니다.</p>
    <Link className="btn mt-4 inline-flex min-h-11 items-center" href="/sites">현장 목록으로 돌아가기</Link>
  </div>;
  return <div className="mx-auto max-w-7xl p-4 sm:p-6">
    <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-xl font-bold text-ink-1">{siteName} · 작업 범위 선택</h1>
        <p className="mt-1 text-sm text-ink-2">외부에서 시작한 요청입니다. 범위와 자료를 고르면 같은 대화에서 이어갈 수 있습니다.</p></div>
      <button type="button" className="btn min-h-11" disabled={Boolean(busy)} onClick={() => { if (dirty) setConfirmReload(true); else void request("refresh"); }}>저장된 선택 불러오기</button>
    </header>
    <div role="alert">{error && <p className="mb-4 rounded border border-line bg-crit-bg p-3 text-sm text-crit-ink">{error}</p>}</div>
    <ConfirmDialog open={confirmReload} title="저장하지 않은 변경이 있습니다"
      description="구역·관측 선택 등 저장하지 않은 변경이 사라지고 저장된 선택으로 돌아갑니다. 외부 대화와 이어지는 작업 자체는 유지됩니다."
      confirmLabel="저장된 선택 불러오기"
      onConfirm={() => { setConfirmReload(false); void request("refresh"); }}
      onCancel={() => setConfirmReload(false)} />
    <p role="status" className="mb-3 text-sm text-ink-2">{busy ? "처리 중입니다. 잠시만 기다려 주세요." : notice}</p>
    {resumeBusy && !busy && <p role="status" className="mb-3 text-sm text-ink-2">최신 상태 확인 중입니다. 입력은 유지됩니다.</p>}
    {resumeFailed && !accessLost && <div className="mb-3 flex flex-wrap items-center gap-2 text-sm leading-6 text-ink-2">
      <p role="status">최신 상태를 확인하지 못했습니다. 지금 보이는 수치·결과는 이전에 불러온 그대로이며, 현재 상태로 새로 확인된 것이 아닙니다. 같은 작업에 새 계산을 요청하지 않았습니다. 연결을 확인한 뒤 다시 확인하거나 ‘저장된 선택 불러오기’로 새로고침하세요.</p>
      <button type="button" className="btn min-h-11" disabled={resumeBusy} onClick={() => void checkRef.current("manual")}>{resumeBusy ? "최신 상태 확인 중…" : "최신 상태 다시 확인"}</button>
    </div>}
    {serverStale && dirty && !resumeFailed && <p className="mb-3 text-sm leading-6 text-ink-2">외부에서 같은 작업이 변경되었습니다. 현재 편집은 유지됩니다. 저장된 최신을 보려면 ‘저장된 선택 불러오기’를 누르세요.</p>}
    {pending && <p className="mb-3 text-sm leading-6 text-ink-2">{followPaused ? "자동 확인이 일시 중지되었습니다." : "실행 중인 같은 작업의 결과를 자동으로 확인합니다. 이 확인으로 새 계산을 요청하지 않습니다."}
      {followPaused && <button type="button" className="btn ml-2 min-h-11" onClick={() => { trackFollowPaused(false); setError(""); setFollowGeneration((value) => value + 1); }}>진행 상태 다시 확인</button>}
    </p>}
    {view.state === "SELECTION_UNAVAILABLE" && <p className="mb-4 text-sm text-high-ink">저장된 구역이나 자료를 지금 사용할 수 없습니다. 사용 가능한 후보로 바꾸거나 담당자에게 권한을 확인하세요.</p>}
    {!canWrite && <p className="mb-4 text-sm text-ink-2">열람 권한으로 접속했습니다. 선택 변경은 권한이 있는 담당자에게 요청하세요.</p>}
    <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[336px_minmax(0,1fr)]">
      <section aria-label="작업 선택" className="space-y-5">
        {canWrite && <p className="text-sm leading-6 text-ink-2 lg:hidden">작은 화면에서는 선택을 저장하거나 분석을 요청할 수 없습니다. 여기서 고른 내용은 화면을 넓히면(1024px 이상) 그대로 저장할 수 있고, 저장된 작업은 이 링크에서 다시 열 수 있습니다.</p>}
        <div><label htmlFor="task-purpose" className="mb-2 block text-sm font-semibold">무엇을 확인할까요?</label>
          <select id="task-purpose" className="input min-h-11 w-full" value={purpose} disabled={!canAct || locked} onChange={(e) => setDraftFields({ purpose: e.target.value as SpatialTaskPurpose })}>
            {Object.entries(TASK_PURPOSE_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
          {(purpose === "DAILY_TARGET" || purpose === "DESIGN_REMAINING") && <p className="mt-2 text-sm text-high-ink">{purpose === "DESIGN_REMAINING" ? "설계면을 기준으로 한 잔여량 계산은 아직 지원하지 않습니다." : "오늘의 작업 목표에는 계획·기한·작업 여건이 필요하며, 현재 분석으로 결정하지 않습니다."} 두 관측 사이 변화로 자동 대체하지 않습니다.</p>}
        </div>
        <fieldset disabled={!canAct || locked}><legend className="mb-2 text-sm font-semibold">어느 구역인가요?</legend>
          <div className="max-h-64 overflow-y-auto divide-y divide-line border-y border-line">
            {options.areas.map((area) => <label key={area.workAreaId} className="flex min-h-12 cursor-pointer items-center gap-3 px-2 py-3 text-sm hover:bg-sunk">
              <input type="radio" name="task-area" value={area.workAreaId} checked={areaId === area.workAreaId} onChange={() => { setDraftFields({ areaId: area.workAreaId, baselineKey: "", currentKey: "" }); }} />
              <span className="break-words">{area.name}</span>
            </label>)}
          </div>
          {options.areas.length === 0 && <p className="mt-2 text-sm text-ink-2">선택 가능한 작업구역이 없습니다. 담당자에게 구역 등록과 이 요청의 접근 범위를 확인해 달라고 요청하세요.</p>}
        </fieldset>
        <p className="text-sm leading-6 text-ink-2">새 범위는 <Link className="underline underline-offset-4" href={`/sites/${encodeURIComponent(siteId)}/work-areas`}>작업구역 관리</Link>에서 등록합니다. 외부 AI의 허용 범위가 자동으로 넓어지지는 않습니다. 이 작업 링크는 그대로 보관하세요.</p>
      </section>
      <section aria-label="선택 범위와 관측" className="min-w-0">
        <h2 className="mb-2 text-base font-semibold">{selectedArea?.name ?? "구역을 고르면 경계를 보여드립니다"}</h2>
        {areas.length ? <WorkAreaChoiceMap areas={areas} selectedId={areaId} disabled={!canAct || locked}
          onSelect={(id) => { if (id !== areaId) { setDraftFields({ areaId: id, baselineKey: "", currentKey: "" }); } }} />
          : <div className="flex min-h-80 items-center justify-center rounded-lg border border-line bg-sunk px-6 text-sm text-ink-2">지도에 표시할 작업구역이 없습니다.</div>}
        <p className="mt-2 text-xs leading-5 text-ink-muted">등록된 구역 경계의 위치 확인용 지도입니다. 배경 지도는 현장 관측 영상이 아니며 정확도·정산 적합성을 증명하지 않습니다.</p>
        {supported && <fieldset className="mt-5 grid gap-3 sm:grid-cols-2" disabled={!canAct || locked || !areaId}>
          <legend className="mb-2 text-sm font-semibold">언제와 언제를 비교할까요?</legend>
          {(["baseline", "current"] as const).map((side) => <label key={side} className="block text-sm">
            <span className="mb-1 block">{side === "baseline" ? "이전 관측" : "이후 관측"}</span>
            <select id={`task-${side}`} className="input min-h-11 w-full" value={side === "baseline" ? baselineKey : currentKey} onChange={(e) => { if (side === "baseline") setDraftFields({ baselineKey: e.target.value }); else setDraftFields({ currentKey: e.target.value }); }}>
              <option value="">관측 선택</option>{candidates.map((item, index) => <option key={selectorKey(item.selector)} value={selectorKey(item.selector)}>{formatKoreanDateTime(item.captureStartedAt)} · 관측 {index + 1} · 자료 개정 {item.selector.revision}</option>)}
            </select>
          </label>)}
          {areaId && candidates.length < 2 && <p className="text-sm text-high-ink sm:col-span-2">이 구역에는 현재 선택할 수 있는 관측이 두 개 미만입니다. 자료 등록·봉인과 접근 범위를 확인하세요. <Link className="underline underline-offset-4" href={`/sites/${encodeURIComponent(siteId)}/spatial-assets?workAreaId=${encodeURIComponent(areaId)}`}>등록 자료와 검사 상태 확인</Link></p>}
          {baselineKey && baselineKey === currentKey && <p className="text-sm text-high-ink sm:col-span-2">서로 다른 두 관측을 선택하세요.</p>}
        </fieldset>}
        {options.nextOffset !== null && <button type="button" className="btn mt-3 min-h-11" disabled={Boolean(busy)} onClick={() => void more()}>관측 더 불러오기</button>}
        {canWrite && <ResponsiveActionBoundary action="ANALYSIS_REQUEST" reason="지도 범위 확정과 분석 요청은 노트북에서 계속하세요. 저장된 작업은 이 링크에서 다시 열 수 있습니다.">
          <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-4">
            {!locked && <button type="button" className="btn btn-primary min-h-11" disabled={!canAct || !dirty}
              aria-describedby={saveHint ? saveHintId : undefined} onClick={() => void request("selection")}>{busy === "selection" ? "선택 저장 중…" : "이 선택으로 계속"}</button>}
            {complete && !dirty && <><button type="button" className="btn min-h-11" disabled={!canAct} onClick={() => void request("readiness")}>분석 조건 확인</button>
              {locked
                ? <button type="button" className="btn btn-primary min-h-11" disabled={!canAct || resumeBusy} onClick={() => void checkRef.current("manual")}>{resumeBusy ? "최신 상태 확인 중…" : "같은 분석 다시 확인"}</button>
                : <button type="button" className="btn btn-primary min-h-11" disabled={!canAct} onClick={() => void request("run")}>두 관측 변화 분석 요청</button>}</>}
            {saveHint && <p id={saveHintId} className="w-full text-sm leading-6 text-ink-2">{saveHint}</p>}
          </div>
        </ResponsiveActionBoundary>}
        {locked && <p className="mt-3 text-sm text-ink-2">분석을 요청한 선택은 고정됩니다. 다른 범위·관측은 외부 대화에서 새 작업으로 시작하세요. ‘같은 분석 다시 확인’은 저장된 결과를 다시 불러오며, 새 계산을 요청하지 않습니다.</p>}
        {!dirty && view.analysis && <section aria-label="같은 구역의 분석 결과" className="mt-5 border-t border-line pt-4">
          <h2 className="text-base font-semibold">{({ NOT_STARTED: "분석이 아직 시작되지 않았습니다", QUEUED: "분석을 기다리고 있습니다", RUNNING: "변화량을 계산하고 있습니다", COMPLETED: "두 관측 사이 지형 변화", FAILED: "분석을 완료하지 못했습니다" })[view.analysis.executionState]}</h2>
          {resumeFailed && result && <div className="mt-2 flex flex-wrap items-center gap-2 text-sm leading-6 text-high-ink">
            <p role="status">이전에 불러온 결과이며 새로 확인되지 않았습니다. 새 계산을 요청하지 않았습니다.</p>
            <button type="button" className="btn min-h-11" disabled={resumeBusy} onClick={() => void checkRef.current("manual")}>{resumeBusy ? "최신 상태 확인 중…" : "최신 상태 다시 확인"}</button>
          </div>}
          {result ? <>
            <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
              <div className="min-w-0"><dt className="text-ink-2">절토</dt><dd className="mt-1 break-words font-semibold tabular-nums">{shownNumber(result.metrics.cutM3)} m³</dd></div>
              <div className="min-w-0"><dt className="text-ink-2">성토</dt><dd className="mt-1 break-words font-semibold tabular-nums">{shownNumber(result.metrics.fillM3)} m³</dd></div>
              <div className="min-w-0"><dt className="text-ink-2">순변화</dt><dd className="mt-1 break-words font-semibold tabular-nums">{shownNumber(result.metrics.netM3)} m³</dd></div>
            </dl>
            {result.metrics.uncertaintyM3 === null ? (
              <p className="mt-2 text-sm leading-6 text-ink-2">불확실성 미기록 — 기록된 값이 없으므로 0으로 볼 수 없습니다. 검사점 평가와 별개입니다.</p>
            ) : typeof result.metrics.uncertaintyM3 === "number" && Number.isFinite(result.metrics.uncertaintyM3) ? (
              <p className="mt-2 break-words text-sm leading-6 text-ink-2 tabular-nums">{`불확실성 ±${shownNumber(result.metrics.uncertaintyM3)} m³ (기록값)`}</p>
            ) : null}
            <p className="mt-3 text-sm leading-6 text-ink-2">위 지도 경계와 선택한 두 관측에 대한 Core 계산입니다. 공통 유효 범위 {shownNumber(result.coverage.commonValidAreaM2)} m² / 선택 범위 {shownNumber(result.coverage.selectedAreaM2)} m². 자료가 없는 셀 {formatCountKo(result.coverage.unavailableCellCount)}개는 0으로 채운 영역이 아닙니다.</p>
            <p className="mt-1 text-xs leading-5 text-ink-muted">지도는 등록된 구역 경계이며, 유효·제외 셀의 분포를 그린 레이어는 아닙니다.</p>
            <AnalysisCoverage detail={view.analysis} />
            <p className="mt-2 text-sm leading-6 text-ink-2">{suitabilityNote(view.analysis.suitabilityState)}</p>
            {result.limitationCodes.length > 0 && <ul aria-label="결과 제한 사항" className="mt-2 space-y-1 text-sm leading-6 text-ink-2">
              {result.limitationCodes.map((code, index) => <li key={`${code}-${index}`}>
                <span>{getAnalysisIssueGuidance(code).label}</span> <code className="break-all text-ink-muted">{code}</code>
              </li>)}
            </ul>}
            <p className="mt-2 text-sm leading-6 text-ink-2">순변화는 성토−절토입니다. 계산 시각 {formatKoreanDateTime(result.computedAt)}. 현장 정확도·정산 적합성과 설계 잔여량·오늘 작업 목표를 뜻하지 않습니다.</p>
          </> : <><p className="mt-2 text-sm leading-6 text-ink-2">현재 제공할 수 있는 수치가 없습니다. 0으로 해석하지 마세요. 외부 대화에서 상태를 확인하거나 저장된 선택을 새로 불러오세요.</p>
            {view.analysis.executionState === "COMPLETED" && <p className="mt-2 text-sm leading-6 text-ink-2">완료된 계산이 있으나 현재 적합성이 확인되지 않아 수치를 제공하지 않습니다. 아래 사유와 보완 방법을 확인하세요.</p>}</>}
        </section>}
        {dirty && <p className="mt-3 text-sm text-ink-2">변경한 선택은 아직 저장되지 않았습니다. 저장하면 외부 대화에서 이어갈 수 있습니다.</p>}
        {!dirty && view.readiness && <section aria-label="조건 확인 결과" className="mt-5 border-t border-line pt-4">
          <h2 className="text-base font-semibold">{issues.length ? "분석 전에 보완이 필요합니다" : "Core 조건 확인을 마쳤습니다"}</h2>
          <p className="mt-1 text-sm text-ink-2">{formatKoreanDateTime(view.readiness.checkedAt)} 기준. 실행 때 다시 점검하며, 유효 범위는 워커 검증이 필요합니다. 현장 정확도는 별도입니다.</p>
          {view.readiness.limitationCodes.length > 0 && <ul aria-label="조건 확인 제한 사항" className="mt-2 space-y-1 text-sm leading-6 text-ink-2">
            {view.readiness.limitationCodes.map((code, index) => <li key={`${code}-${index}`}>
              <span>{getAnalysisIssueGuidance(code).label}</span> <code className="break-all text-ink-muted">{code}</code>
            </li>)}
          </ul>}
        </section>}
        {issues.length > 0 && <ul className="mt-3 space-y-3">{issues.map((issue, index) => {
          const guidance = getAnalysisIssueGuidance(issue.code);
          return <li key={`${issue.code}-${index}`} className="text-sm"><p className="font-semibold">{guidance.label}</p><p className="mt-1 text-ink-2">{guidance.selfServiceNextStep ?? guidance.nextStep}</p></li>;
        })}</ul>}
        {view.task.analysisId && <Link className="btn mt-4 inline-flex min-h-11 items-center" href={`/sites/${encodeURIComponent(siteId)}/analysis?analysisId=${encodeURIComponent(view.task.analysisId)}`}>분석 기록·근거 자세히</Link>}
      </section>
    </div>
    <footer className="mt-6 border-t border-line pt-3 text-xs leading-5 text-ink-muted">선택 링크 유효기한: {formatKoreanDateTime(view.task.expiresAt)} · 외부 대화가 자동으로 갱신되지 않으면 ‘선택했어’라고 알려주세요. 토큰이나 좌표를 복사할 필요는 없습니다.</footer>
  </div>;
}
