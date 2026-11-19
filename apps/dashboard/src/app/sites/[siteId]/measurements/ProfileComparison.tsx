"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { InlineNotice } from "@/components/ui/InlineNotice";
import { Disclosure } from "@/components/ui/Disclosure";
import { isJobView, isSurfaceProfileComparison, type MeasurementFeatureRef, type SurfaceProfileComparison } from "@/lib/core-api/measurement-types";
import { explainExternalUseDecision } from "@/lib/external-use-blockers";
import { nearestSample } from "@/lib/measurement-profile";

import { ProfileDifferenceChart } from "./ProfileChart";

type PairSide = { jobId: string; assetRef: string; label: string; spacingM: number; lineLengthM: number };
type Pair = { baseline: PairSide; current: PairSide };

// Keep retry keys across selection-driven remounts inside the SPA. Unknown transport
// outcomes can then be retried idempotently if the operator returns to the same pair.
const requestKeys = new Map<string, string>();

function idempotencyKey(fingerprint: string): string {
  const existing = requestKeys.get(fingerprint);
  if (existing) return existing;
  const created = `console-${crypto.randomUUID()}`;
  requestKeys.set(fingerprint, created);
  if (requestKeys.size > 100) requestKeys.delete(requestKeys.keys().next().value!);
  return created;
}

function reasonText(code: string): string {
  const guide = explainExternalUseDecision([code], ["RESOLVE_EXTERNAL_USE_BLOCKER"]);
  return guide.known ? `${guide.title} ${guide.explanation} ${guide.step}` : `${code}: ${guide.explanation}`;
}

function blockerText(reasons: readonly string[], remediations: readonly string[]): { title: string; explanation: string; step: string; ownerLabel: string; codes: string[] } {
  const guide = explainExternalUseDecision(reasons, remediations);
  return {
    title: guide.title,
    explanation: guide.explanation,
    step: guide.step,
    ownerLabel: guide.ownerLabel,
    codes: guide.codes,
  };
}

function csvField(value: string | number | null): string {
  if (value === null) return "";
  if (typeof value === "number") return String(value);
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return `"${safe.replaceAll('"', '""')}"`;
}

function download(name: string, comparison: SurfaceProfileComparison, pair: Pair, feature: MeasurementFeatureRef) {
  if (!comparison.result) return;
  const rows = [
    ["comparison_digest", comparison.result.comparisonDigest],
    ["decision_id", comparison.decisionId],
    ["decision_digest", comparison.decisionDigest],
    ["baseline_capture_label", pair.baseline.label],
    ["current_capture_label", pair.current.label],
    ["baseline_job_id", comparison.baselineJobId],
    ["current_job_id", comparison.currentJobId],
    ["baseline_asset_ref", pair.baseline.assetRef],
    ["current_asset_ref", pair.current.assetRef],
    ["feature_id", feature.featureId],
    ["feature_revision", feature.revision],
    ["feature_line_digest", feature.lineDigest],
    ["baseline_result_digest", comparison.result.baselineResultDigest],
    ["current_result_digest", comparison.result.currentResultDigest],
    ["distance_unit", "m"],
    ["height_unit", "m"],
    ["difference_definition", "current_minus_baseline"],
    [],
    ["distance_m", "baseline_m", "current_m", "difference_m", "unknown_reason"],
    ...comparison.result.samples.map((sample) => [
      sample.distanceM,
      sample.baselineM,
      sample.currentM,
      sample.differenceM,
      sample.invalidReason,
    ]),
  ];
  const text = `\uFEFF${rows.map((row) => row.map(csvField).join(",")).join("\r\n")}`;
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function BlockedDecisionCopy({
  guide,
  pair,
  address,
}: {
  guide: ReturnType<typeof blockerText>;
  pair: Pair;
  address: string;
}) {
  const [feedback, setFeedback] = useState<{ status: "copied" } | { status: "fallback"; text: string } | null>(null);
  const fallbackRef = useRef<HTMLTextAreaElement | null>(null);

  useLayoutEffect(() => {
    if (feedback?.status !== "fallback") return;
    fallbackRef.current?.focus();
    fallbackRef.current?.select();
  }, [feedback]);

  async function copyDecision() {
    const decisionText = [
      "두 시점 높이차 판정",
      guide.title,
      guide.explanation,
      `담당 ${guide.ownerLabel} · ${guide.step}`,
      `기준 자료 ${pair.baseline.label} · ${pair.baseline.assetRef}`,
      `현재 자료 ${pair.current.label} · ${pair.current.assetRef}`,
      `판정·조치 코드 ${guide.codes.join(", ")}`,
      new URL(address, window.location.origin).toString(),
    ].join("\n");
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard access is unavailable");
      await navigator.clipboard.writeText(decisionText);
      setFeedback({ status: "copied" });
    } catch {
      setFeedback({ status: "fallback", text: decisionText });
    }
  }

  return (
    <>
      <button type="button" className="btn mt-3" onClick={() => void copyDecision()}>
        판정 내용 복사
      </button>
      {feedback?.status === "copied" && (
        <p role="status" aria-live="polite" className="mt-2">판정 내용을 복사했습니다.</p>
      )}
      {feedback?.status === "fallback" && (
        <div className="mt-2">
          <p id="profile-comparison-copy-help" className="text-caption">
            클립보드에 접근할 수 없습니다. 아래 내용을 선택해 직접 복사하세요.
          </p>
          <textarea
            ref={fallbackRef}
            aria-label="복사할 판정 내용"
            aria-describedby="profile-comparison-copy-help"
            readOnly
            rows={8}
            value={feedback.text}
            onFocus={(event) => event.currentTarget.select()}
            className="mt-2 w-full rounded-md border border-line bg-surface p-2 text-caption focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          />
        </div>
      )}
    </>
  );
}

export function ProfileComparison({ siteId, workAreaId, feature, canCompare, canRequest, pair, probeM, onProbe, savedComparison }: {
  siteId: string;
  workAreaId: string;
  feature: MeasurementFeatureRef;
  canCompare: boolean;
  canRequest: boolean;
  pair: Pair | null;
  savedComparison: SurfaceProfileComparison | null;
  probeM: number | null;
  onProbe: (distanceM: number | null) => void;
}) {
  const router = useRouter();
  const pairKey = pair ? `${pair.baseline.jobId}:${pair.current.jobId}` : null;
  const [stored, setStored] = useState<{ pairKey: string; comparison: SurfaceProfileComparison } | null>(
    savedComparison && pairKey ? { pairKey, comparison: savedComparison } : null,
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const comparison = stored?.pairKey === pairKey ? stored.comparison : null;
  function permalink(value: SurfaceProfileComparison): string {
    const query = new URLSearchParams({
      workAreaId, feature: feature.featureId, ref: value.baselineJobId, cur: value.currentJobId, comparison: value.decisionId,
    });
    return `/sites/${encodeURIComponent(siteId)}/measurements?${query}`;
  }
  const spacingMismatch = Boolean(pair && pair.baseline.spacingM !== pair.current.spacingM);
  const commonSpacingM = pair ? Math.max(pair.baseline.spacingM, pair.current.spacingM) : null;
  const reReadSides = pair && commonSpacingM !== null
    ? [
        ...(pair.baseline.spacingM < commonSpacingM ? [{ role: "baseline" as const, side: pair.baseline }] : []),
        ...(pair.current.spacingM < commonSpacingM ? [{ role: "current" as const, side: pair.current }] : []),
      ]
    : [];
  const copyIdentity = pair && comparison
    ? JSON.stringify([
      siteId, workAreaId, pair.baseline.jobId, pair.baseline.label, pair.baseline.assetRef,
      pair.current.jobId, pair.current.label, pair.current.assetRef, feature.featureId,
      feature.revision, feature.lineDigest, comparison.decisionId,
    ])
    : null;
  useLayoutEffect(() => () => {
    activeRequest.current?.abort();
    activeRequest.current = null;
  }, []);

  async function readComparison(currentPair: Pair, decisionId: string, signal: AbortSignal): Promise<SurfaceProfileComparison> {
    const query = new URLSearchParams({
      baseline_job_id: currentPair.baseline.jobId,
      current_job_id: currentPair.current.jobId,
      decision_id: decisionId,
    });
    const response = await fetch(
      `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/surface-profile-comparisons?${query}`,
      { cache: "no-store", signal },
    );
    const payload: unknown = await response.json().catch(() => null);
    if (signal.aborted) throw new DOMException("Request aborted", "AbortError");
    if (!response.ok) {
      const body = typeof payload === "object" && payload !== null ? payload as { code?: unknown; reason?: unknown } : null;
      const code = typeof body?.code === "string" ? body.code : typeof body?.reason === "string" ? body.reason : null;
      if (response.status === 409 && code === "PROFILE_COMPARISON_NO_LONGER_ELIGIBLE") {
        requestKeys.delete(`${siteId}:${workAreaId}:${currentPair.baseline.jobId}:${currentPair.current.jobId}`);
        throw new Error("현재 비교 승인이 철회되었거나 자료가 바뀌었습니다. 저장된 숫자를 숨겼습니다. 최신 상태에서 새 비교를 요청하세요.");
      }
      if (code) throw new Error(reasonText(code));
      throw new Error("두 시점 비교를 다시 확인할 수 없습니다. 권한과 연결 상태를 확인하세요.");
    }
    if (!isSurfaceProfileComparison(payload)
      || payload.baselineJobId !== currentPair.baseline.jobId
      || payload.currentJobId !== currentPair.current.jobId
      || payload.decisionId !== decisionId) {
      throw new Error("서버 응답이 선택한 두 단면에 묶여 있지 않아 표시하지 않았습니다.");
    }
    return payload;
  }

  async function request() {
    if (!pair || busy || !canCompare || spacingMismatch) return;
    setBusy(true);
    setMessage(null);
    setStored(null);
    const controller = new AbortController();
    activeRequest.current = controller;
    const fingerprint = `${siteId}:${workAreaId}:${pair.baseline.jobId}:${pair.current.jobId}`;
    try {
      const key = idempotencyKey(fingerprint);
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/surface-profile-comparisons`,
        {
          method: "POST",
          headers: { "content-type": "application/json", "Idempotency-Key": key },
          body: JSON.stringify({ baselineJobId: pair.baseline.jobId, currentJobId: pair.current.jobId }),
          signal: controller.signal,
        },
      );
      const payload: unknown = await response.json().catch(() => null);
      if (controller.signal.aborted) return;
      if (!response.ok) {
        if (response.status < 500) requestKeys.delete(fingerprint);
        const body = typeof payload === "object" && payload !== null ? payload as { reason?: unknown; reasonCode?: unknown; code?: unknown } : null;
        const rawCode = body?.reasonCode ?? body?.code ?? body?.reason;
        const code = typeof rawCode === "string" && /^[A-Z][A-Z0-9_]{1,63}$/.test(rawCode) ? rawCode : null;
        if (code === "PROFILE_COMPARISON_NO_LONGER_ELIGIBLE") {
          requestKeys.delete(fingerprint);
          throw new Error("현재 자료나 승인 상태가 달라 숫자를 내보내지 않았습니다. 최신 상태로 새 비교를 다시 요청하세요.");
        }
        throw new Error(code ? reasonText(code) : "두 시점 비교를 요청하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.");
      }
      if (!isSurfaceProfileComparison(payload)
        || payload.baselineJobId !== pair.baseline.jobId
        || payload.currentJobId !== pair.current.jobId) {
        throw new Error("서버 응답이 선택한 두 단면에 묶여 있지 않아 표시하지 않았습니다.");
      }
      // A valid BLOCKED or ELIGIBLE decision is a completed assessment. A deliberate
      // follow-up must get a fresh decision; only unknown transport outcomes reuse the key.
      requestKeys.delete(fingerprint);
      setStored({ pairKey: pairKey!, comparison: payload });
      if (window.location.pathname === `/sites/${encodeURIComponent(siteId)}/measurements`) {
        window.history.replaceState(null, "", permalink(payload));
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setStored(null);
        setMessage(error instanceof Error ? error.message : "두 시점 비교를 요청하지 못했습니다.");
      }
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function requestCommonSpacing() {
    if (!pair || !canRequest || !commonSpacingM || reReadSides.length === 0 || busy) return;
    setBusy(true);
    setMessage(null);
    setStored(null);
    const controller = new AbortController();
    activeRequest.current = controller;
    const created: { role: "baseline" | "current"; jobId: string }[] = [];
    let navigating = false;
    try {
      for (const target of reReadSides) {
        const fingerprint = `${siteId}:${workAreaId}:${target.side.jobId}:${target.side.assetRef}:${feature.featureId}:${feature.revision}:${feature.lineDigest}:${commonSpacingM}`;
        const key = idempotencyKey(fingerprint);
        const response = await fetch(
          `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/surface-profile-requests`,
          {
            method: "POST",
            headers: { "content-type": "application/json", "Idempotency-Key": key },
            body: JSON.stringify({ assetRef: target.side.assetRef, feature, sampleSpacingM: commonSpacingM }),
            signal: controller.signal,
          },
        );
        const payload: unknown = await response.json().catch(() => null);
        if (controller.signal.aborted) return;
        const body = typeof payload === "object" && payload !== null ? payload as { job?: unknown; code?: unknown; decision?: unknown } : null;
        if (!response.ok) {
          if (response.status < 500) requestKeys.delete(fingerprint);
          const decision = typeof body?.decision === "object" && body.decision !== null ? body.decision as { reasons?: unknown; remediations?: unknown } : null;
          const blockers = Array.isArray(decision?.reasons) ? decision.reasons.filter((code): code is string => typeof code === "string") : [];
          const remediations = Array.isArray(decision?.remediations) ? decision.remediations.filter((code): code is string => typeof code === "string") : [];
          const code = typeof body?.code === "string" ? body.code : null;
          const decisionGuide = blockers.length > 0 ? blockerText(blockers, remediations) : null;
          throw new Error(decisionGuide ? `${decisionGuide.title} ${decisionGuide.explanation} ${decisionGuide.step}` : code ? reasonText(code) : "단면을 다시 요청하지 못했습니다.");
        }
        const job = body?.job;
        if (!isJobView(job)
          || job.siteId !== siteId
          || job.workAreaId !== workAreaId
          || job.assetRef !== target.side.assetRef
          || job.feature.featureId !== feature.featureId
          || job.feature.revision !== feature.revision
          || job.feature.lineDigest !== feature.lineDigest) {
          throw new Error("새 작업이 선택한 자료와 저장 선 개정에 묶이지 않아 선택을 바꾸지 않았습니다.");
        }
        requestKeys.delete(fingerprint);
        created.push({ role: target.role, jobId: job.jobId });
      }
      if (created.length > 0 && !controller.signal.aborted) {
        const url = new URL(window.location.href);
        url.searchParams.delete("comparison");
        for (const item of created) url.searchParams.set(item.role === "baseline" ? "ref" : "cur", item.jobId);
        navigating = true;
        router.replace(`${url.pathname}${url.search}${url.hash}`, { scroll: false });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setStored(null);
        setMessage(error instanceof Error ? error.message : "단면을 다시 요청하지 못했습니다.");
      }
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
      if (!navigating && !controller.signal.aborted) setBusy(false);
    }
  }

  async function exportCsv() {
    if (!pair || !comparison || comparison.verdict !== "ELIGIBLE" || spacingMismatch) return;
    setBusy(true);
    setMessage(null);
    const controller = new AbortController();
    activeRequest.current = controller;
    try {
      const fresh = await readComparison(pair, comparison.decisionId, controller.signal);
      if (controller.signal.aborted) return;
      if (fresh.verdict !== "ELIGIBLE" || !fresh.result
        || fresh.decisionDigest !== comparison.decisionDigest
        || fresh.result.comparisonDigest !== comparison.result?.comparisonDigest
        || fresh.result.baselineResultDigest !== comparison.result?.baselineResultDigest
        || fresh.result.currentResultDigest !== comparison.result?.currentResultDigest) {
        setStored({ pairKey: pairKey!, comparison: fresh });
        throw new Error("현재 비교 권한이나 결과가 달라져 CSV를 만들지 않았습니다. 다시 확인하세요.");
      }
      if (controller.signal.aborted) return;
      download(`profile-difference-${pair.baseline.jobId.slice(-8)}-${pair.current.jobId.slice(-8)}.csv`, fresh, pair, feature);
    } catch (error) {
      if (!controller.signal.aborted) {
        setStored(null);
        setMessage(error instanceof Error ? error.message : "최신 비교 확인에 실패했습니다.");
      }
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  if (!pair) return null;
  const result = !spacingMismatch && comparison?.verdict === "ELIGIBLE" ? comparison.result : null;
  const rise = result?.largestRiseM !== null && result?.largestRiseM !== undefined && result.largestRiseM > 0
    ? `+${result.largestRiseM.toFixed(2)} m`
    : "값 없음";
  const drop = result?.largestDropM !== null && result?.largestDropM !== undefined && result.largestDropM < 0
    ? `−${Math.abs(result.largestDropM).toFixed(2)} m`
    : "값 없음";
  const targetNames = reReadSides.map((target) => target.role === "baseline" ? "기준" : "현재").join("·");
  const blockedGuide = comparison?.verdict === "BLOCKED"
    ? blockerText(comparison.reasons, comparison.remediations)
    : null;
  const probeSample = result && probeM !== null ? nearestSample(result.samples, probeM) : null;
  const probeText = probeSample === null
    ? ""
    : probeSample.differenceM === null
      ? `${probeSample.distanceM.toFixed(1)} m · 값 없음 · ${probeSample.invalidReason === "BASELINE_UNAVAILABLE" ? "기준 자료 없음" : probeSample.invalidReason === "CURRENT_UNAVAILABLE" ? "현재 자료 없음" : "양쪽 자료 없음"}`
      : `${probeSample.distanceM.toFixed(1)} m · 높이차 ${probeSample.differenceM > 0 ? "+" : probeSample.differenceM < 0 ? "−" : ""}${Math.abs(probeSample.differenceM).toFixed(2)} m`;

  return (
    <section aria-label="두 시점 높이차" className="@container mt-5 border-t border-line pt-4 lg:col-start-1 lg:row-start-2 lg:mt-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lead font-semibold">두 시점 높이차</h3>
          <p className="mt-1 text-caption text-ink-muted">같은 저장 선의 두 단면을 Core가 확인한 뒤 높이차를 계산합니다.</p>
          <p className="mt-1 text-caption">기준 {pair.baseline.label} → 현재 {pair.current.label}</p>
        </div>
        {!spacingMismatch && canCompare && (
          <button type="button" className="btn hidden lg:inline-flex" disabled={busy} onClick={() => void request()}>
            {busy ? "확인 중…" : comparison ? "다시 확인" : "두 시점 높이차 확인"}
          </button>
        )}
      </div>

      {spacingMismatch ? (
        <InlineNotice tone="high" role="status" className="mt-3">
          <p>표본 간격이 다릅니다. 기준 {pair.baseline.spacingM} m, 현재 {pair.current.spacingM} m입니다.</p>
          <p className="mt-1">공통 간격 {commonSpacingM?.toFixed(3)} m에 맞춰 {targetNames} 자료만 다시 읽으면 두 날짜를 비교할 수 있습니다. 선택한 저장 선 개정과 자료는 그대로 사용합니다.</p>
          {canRequest
            ? <button type="button" className="btn mt-2 hidden lg:inline-flex" disabled={busy} onClick={() => void requestCommonSpacing()}>
              {busy ? "단면 다시 읽는 중…" : `공통 표본 간격으로 다시 읽기 · ${targetNames}`}
            </button>
            : <p className="mt-2">다시 읽기에는 단면 작업 등록 권한이 필요합니다.</p>}
          <p className="mt-2 text-micro text-ink-muted lg:hidden">표본 간격 맞춤 요청은 화면 폭 1024px 이상에서 할 수 있습니다.</p>
        </InlineNotice>
      ) : (
        <>
          <p className="mt-2 text-caption text-ink-muted lg:hidden">두 시점 비교 요청은 화면 폭 1024px 이상에서 할 수 있습니다.</p>
          {!canCompare && <p className="mt-2 text-caption text-ink-muted">비교 판정에는 작업 수정 권한과 자료 읽기 권한이 필요합니다.</p>}
        </>
      )}

      {message && <InlineNotice tone="high" role="alert" className="mt-3">{message}</InlineNotice>}
      {!spacingMismatch && comparison?.verdict === "BLOCKED" && blockedGuide && (
        <InlineNotice tone="high" role="status" className="mt-3">
          <p className="font-semibold">{blockedGuide.title}</p>
          <p className="mt-1">{blockedGuide.explanation}</p>
          <p className="mt-1">{blockedGuide.step} 담당: {blockedGuide.ownerLabel}</p>
          {copyIdentity && (
            <BlockedDecisionCopy
              key={copyIdentity}
              guide={blockedGuide}
              pair={pair}
              address={permalink(comparison)}
            />
          )}
          <Disclosure label="Core 판정 사유와 조치 코드" className="mt-2 text-micro">
            <p className="mt-1 break-all">사유: {comparison.reasons.join(", ")}</p>
            <p className="break-all">조치: {comparison.remediations.join(", ")}</p>
          </Disclosure>
        </InlineNotice>
      )}
      {result && comparison && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-3 text-caption @2xl:grid-cols-3">
            <p>값 있는 지점 <strong className="tabular">{result.validCount}</strong> / {result.samples.length}</p>
            <p>가장 큰 상승 <strong className="tabular">{rise}</strong></p>
            <p>가장 큰 하강 <strong className="tabular">{drop}</strong></p>
          </div>
          <p className="mt-2 text-micro text-ink-muted">높이차는 현재에서 기준을 뺀 값입니다. 값이 없는 지점은 계산하지 않습니다.</p>
          <div className="mt-3 grid min-w-0 grid-cols-1 items-start gap-3 @2xl:grid-cols-2">
            <div className="min-w-0 rounded-lg border border-line px-3 py-2">
              <div className="flex items-center justify-between gap-2 text-caption">
                <h4 className="font-semibold">선 방향 높이차</h4>
                <span className="text-micro text-ink-muted">실선 · 0 m 기준</span>
              </div>
              <ProfileDifferenceChart className="mx-auto w-full max-w-[360px]" samples={result.samples} lengthM={pair.baseline.lineLengthM} probeM={probeM} onProbe={onProbe} />
              <p aria-live="polite" className="min-h-5 text-caption tabular">{probeText || "그래프에서 거리를 가리켜 높이차와 지도 위치를 확인하세요."}</p>
            </div>
            <div role="region" aria-label="거리별 두 시점 높이차 표" tabIndex={0} className="max-h-64 min-w-0 overflow-auto rounded-lg border border-line focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
            <table className="tabular w-full border-collapse text-caption">
              <thead><tr className="text-ink-muted"><th className="px-2 py-2 text-left">거리 (m)</th><th className="px-2 py-2 text-right">기준 (m)</th><th className="px-2 py-2 text-right">현재 (m)</th><th className="px-2 py-2 text-right">높이차 (m)</th></tr></thead>
              <tbody>{result.samples.map((sample, index) => (
                <tr key={index} className="border-t border-line">
                  <td className="px-2 py-1.5">{sample.distanceM.toFixed(1)}</td>
                  <td className="px-2 py-1.5 text-right">{sample.baselineM === null ? "값 없음" : sample.baselineM.toFixed(2)}</td>
                  <td className="px-2 py-1.5 text-right">{sample.currentM === null ? "값 없음" : sample.currentM.toFixed(2)}</td>
                  <td className="px-2 py-1.5 text-right">{sample.differenceM === null ? <span title={sample.invalidReason ?? ""}>값 없음 · {sample.invalidReason === "BASELINE_UNAVAILABLE" ? "기준 자료 없음" : sample.invalidReason === "CURRENT_UNAVAILABLE" ? "현재 자료 없음" : "양쪽 자료 없음"}</span> : sample.differenceM.toFixed(2)}</td>
                </tr>
              ))}</tbody>
            </table>
            </div>
          </div>
          <Disclosure label="비교 근거" className="mt-3 text-micro text-ink-muted">
            <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 break-all">
              <dt>판정</dt><dd>{comparison.decisionDigest}</dd>
              <dt>비교 결과</dt><dd>{result.comparisonDigest}</dd>
              <dt>기준 단면</dt><dd>{result.baselineResultDigest}</dd>
              <dt>현재 단면</dt><dd>{result.currentResultDigest}</dd>
            </dl>
          </Disclosure>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void exportCsv()}>
              {busy ? "최신 권한 확인 중…" : "높이차 CSV 내보내기"}
            </button>
            <a href={permalink(comparison)} className="text-caption underline underline-offset-2">이 비교의 고유 주소</a>
          </div>
        </>
      )}
    </section>
  );
}
