"use client";

import { useEffect, useRef, useState } from "react";

import { InlineNotice } from "@/components/ui/InlineNotice";
import { isProfileResultView } from "@/lib/core-api/measurement-types";
import { resultErrorText } from "@/lib/measurement-copy";
import { profileCsv } from "@/lib/measurement-profile";
import { verticalCsvCode } from "@/lib/measurement-vertical";

import type { LoadedSeries } from "./MeasurementWorkbench";

export function ProfileHeightExport({ siteId, workAreaId, featureId, baseline, current }: {
  siteId: string;
  workAreaId: string;
  featureId: string;
  baseline: LoadedSeries | null;
  current: LoadedSeries | null;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);

  async function exportCsv() {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setMessage(null);
    try {
      const selected = [baseline, current].filter((item): item is LoadedSeries => item !== null);
      const series = await Promise.all(selected.map(async (item) => {
        const root = `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}`;
        const response = await fetch(`${root}/surface-profile-jobs/${encodeURIComponent(item.jobId)}/result`, {
          cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error(resultErrorText(response.status));
        const view: unknown = await response.json();
        if (!isProfileResultView(view) || view.job.jobId !== item.jobId
          || view.job.siteId !== siteId || view.job.workAreaId !== workAreaId
          || view.job.executionState !== "COMPLETED" || view.job.availability !== "AVAILABLE"
          || !item.result.resultDigest || view.result.resultDigest !== item.result.resultDigest
          || view.result.assetRef !== item.result.assetRef || view.result.lineDigest !== item.result.lineDigest
          || !view.result.feature || view.result.feature.featureId !== item.result.feature?.featureId
          || view.result.feature.revision !== item.result.feature.revision) {
          throw new Error("선택한 측정 선의 결과가 달라졌습니다. 새로 고침한 뒤 다시 내보내세요.");
        }
        return {
          label: `${item === current ? "현재" : "기준"} ${item.label}`,
          samples: view.result.samples,
          vertical: verticalCsvCode(view.job.receipt?.verticalReference),
        };
      }));
      if (controller.signal.aborted) return;
      const href = URL.createObjectURL(new Blob([profileCsv(series)], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = `profile-${featureId.slice(3, 11)}.csv`;
      document.body.append(anchor);
      try {
        anchor.click();
      } finally {
        anchor.remove();
        URL.revokeObjectURL(href);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setMessage(error instanceof Error ? error.message : "단면을 다시 읽지 못했습니다.");
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      pending.current = null;
    }
  }

  return (
    <div className="mt-4">
      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void exportCsv()}>
        {busy ? "읽기 권한 확인 중…" : "날짜별 높이 CSV 내보내기"}
      </button>
      {message && <InlineNotice role="alert" tone="high" className="mt-2">{message}</InlineNotice>}
    </div>
  );
}
