"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { presentExternalInspectionStatus } from "@/app/field/external-reconstruction-status";
import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";
import type { UploadFlowResult } from "@/lib/site-upload-flow";

const POLL_DELAY_MS = 4_000;
const MAX_CHECKS = 30;

type ReadInspection = (result: UploadFlowResult, signal: AbortSignal) => Promise<ExternalArtifactInspectionView | null>;
type Check = { view: ExternalArtifactInspectionView | null; state: "loading" | "received" | "unavailable" | "paused" };
const loading: Check = { view: null, state: "loading" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function measuredDsm(view: ExternalArtifactInspectionView | null): Record<string, unknown> | null {
  if (view?.registrationState !== "SEALED" || view.sealState !== "SEALED" || view.inspection.state !== "INSPECTION_REPORTED") return null;
  const { outcome, report } = view.inspection;
  if (!Array.isArray(outcome) || !outcome.some((item) => item?.artifactId === "dsm" && item.outcome === "MEASURED")) return null;
  const payload = isRecord(report) ? report.measurementPayload : null;
  if (!isRecord(payload) || !Array.isArray(payload.outcomes)) return null;
  const dsm = payload.outcomes.find((item) => isRecord(item) && item.artifactId === "dsm" && item.outcome === "MEASURED");
  return isRecord(dsm) && isRecord(dsm.measurements) ? dsm.measurements : null;
}

export function UploadCompletion({ result, readInspection, hasDsm, hasOrtho, assetHref, mapHref, onReset }: {
  result: UploadFlowResult;
  readInspection: ReadInspection;
  hasDsm: boolean;
  hasOrtho: boolean;
  assetHref: string;
  mapHref: string;
  onReset: () => void;
}) {
  const [check, setCheck] = useState<Check>(loading);
  const [refresh, setRefresh] = useState(0);
  const artifacts = useMemo(() => [
    ...(hasOrtho ? [{ artifactId: "ortho", kind: "ortho" }] : []),
    ...(hasDsm ? [{ artifactId: "dsm", kind: "dsm" }] : []),
  ], [hasOrtho, hasDsm]);

  useEffect(() => {
    const controller = new AbortController();
    let checks = 0;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      checks += 1;
      let view: ExternalArtifactInspectionView | null = null;
      try {
        view = await readInspection(result, controller.signal);
      } catch {
        // The upload is already sealed. Only its current inspection status is unknown.
      }
      if (controller.signal.aborted) return;
      const pending = !view || presentExternalInspectionStatus(view, artifacts).autoRefresh;
      if (pending && checks === MAX_CHECKS) {
        setCheck({ state: "paused", view });
        return;
      }
      setCheck({ state: view ? "received" : "unavailable", view });
      if (pending) timer = setTimeout(poll, POLL_DELAY_MS);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [result, readInspection, refresh, artifacts]);

  const { view, state } = check;
  const status = view && presentExternalInspectionStatus(view, artifacts);
  const dsm = hasDsm ? measuredDsm(view) : null;
  const needsDatum = dsm?.observedVerticalReference === null;
  const onlyDsmMeasured = !hasOrtho && !!dsm;
  function recheck() {
    setCheck(loading);
    setRefresh((current) => current + 1);
  }

  return (
    <section className="flex flex-col gap-3 self-start rounded-xl border border-line bg-surface p-4">
      <h3 className="text-lead font-bold">올리기가 끝났습니다</h3>
      <div role="status" className="space-y-1 text-body text-ink-2">
        {onlyDsmMeasured ? <p className="font-semibold text-ink-1">DSM 파일 검사 완료</p> : status ? (
          <>
            <p className="font-semibold text-ink-1">{status.title}</p>
            <p>{status.nextAction}</p>
          </>
        ) : (
          <p>{state === "loading" ? "파일 검사 상태를 확인하고 있습니다." : "파일 업로드는 마쳤지만 검사 상태를 확인하지 못했습니다."}</p>
        )}
        {status && status.artifactReasons.length > 0 && (
          <ul className="text-caption text-high-ink">{status.artifactReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        )}
        {state === "paused" && <p className="text-caption text-ink-muted">자동 확인을 마쳤습니다. 검사 상태를 다시 확인할 수 있습니다.</p>}
      </div>
      {needsDatum && <p className="rounded-lg bg-high-bg px-3 py-2 text-body text-high-ink">파일 검사에서 DSM의 높이 기준을 확인하지 못했습니다. 기준을 알고 있다면 자료 상세에서 선언할 수 있습니다.</p>}
      <div className="grid grid-cols-2 gap-2">
        <Link href={assetHref} prefetch={false} className="btn btn-primary col-span-2">{needsDatum ? "자료에서 높이 기준 선택" : "자료 보기"}</Link>
        <Link href={mapHref} className="btn">지도에서 보기</Link>
        <Link href={`/field/work-orders/${encodeURIComponent(result.workOrderId)}`} prefetch={false} className="btn">등록 상태 보기</Link>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" disabled={state === "loading"} className="tap-target text-caption text-ink-2 underline" onClick={recheck}>검사 상태 다시 확인</button>
        <button type="button" className="tap-target hidden text-caption text-ink-2 underline lg:inline-flex" onClick={onReset}>하나 더 올리기</button>
      </div>
    </section>
  );
}
