"use client";

import { useEffect, useRef, useState } from "react";
import { coverageFitsDisplay, isCoverageResourceFor, type AnalysisCoverageResource } from "@/lib/analysis-coverage";
import type { AnalysisView } from "@/lib/core-api/analysis";
import { CoverageGridView } from "./CoverageGridView";
import { AnalysisCoverageMap } from "./AnalysisCoverageMap";

function failure(status: number): string {
  if (status === 401) return "로그인이 만료되었습니다. 다시 로그인한 뒤 이 결과로 돌아오세요.";
  if (status === 403 || status === 404) return "현재 계산 범위를 볼 수 없습니다. 접근 권한과 자료의 현재 사용 가능 상태를 확인하세요.";
  if (status === 409) return "결과의 사용 조건이 바뀌었습니다. 분석 기록을 새로 불러온 뒤 다시 확인하세요.";
  if (status === 413) return "범위 근거가 화면 표시 한도를 넘었습니다. 수치·근거 기록은 별도로 유지되며 빈 영역으로 바꾸지 않습니다.";
  return "계산 범위를 불러오지 못했습니다. 연결을 확인하고 다시 시도하세요. 수치 결과는 별도로 유지됩니다.";
}

function CoverageReader({ detail }: { detail: AnalysisView }) {
  const [resource, setResource] = useState<AnalysisCoverageResource | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [mapOpen, setMapOpen] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => { controller.current?.abort(); }, []);
  async function load() {
    controller.current?.abort();
    const current = new AbortController(); controller.current = current;
    setBusy(true); setError(""); setResource(null); setMapOpen(false);
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(detail.siteId)}/analyses/${encodeURIComponent(detail.analysisId)}/coverage`,
        { cache: "no-store", signal: current.signal });
      if (current.signal.aborted) return;
      if (!response.ok) { setError(failure(response.status)); return; }
      const value: unknown = await response.json();
      if (current.signal.aborted) return;
      if (!isCoverageResourceFor(value, detail)) { setError("계산 범위와 이 결과의 연결을 확인할 수 없습니다. 분석 기록을 새로 불러온 뒤 다시 확인하세요."); return; }
      setResource(value);
    } catch {
      if (!current.signal.aborted) setError(failure(0));
    } finally { if (!current.signal.aborted) setBusy(false); }
  }
  return <div className="mt-3 border-t border-line pt-3">
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="btn min-h-11" disabled={busy} onClick={() => void load()}>{resource ? "계산 범위 다시 확인" : "계산·제외 영역 보기"}</button>
      {busy && <button type="button" className="btn min-h-11" onClick={() => { controller.current?.abort(); setBusy(false); }}>불러오기 취소</button>}
    </div>
    <p role="status" className="mt-2 text-xs leading-5 text-ink-2">{busy ? "Core에 보관된 범위 근거를 확인하고 있습니다." : "등록된 구역 경계와 실제 계산 셀은 다를 수 있습니다. 저장된 셀 근거를 확인하세요."}</p>
    <div role="alert" className="mt-1 text-sm leading-6 text-high-ink">{error}</div>
    {resource && <CoverageGridView witness={resource.coverage} />}
    {resource?.gridReference && <>
      <button type="button" className="btn mt-3 min-h-11" aria-expanded={mapOpen} onClick={() => setMapOpen((value) => !value)}>{mapOpen ? "위치 지도 닫기" : "지도에서 계산 범위 보기"}</button>
      {mapOpen && <AnalysisCoverageMap witness={resource.coverage} reference={resource.gridReference} />}
    </>}
    {resource && !resource.gridReference && <p className="mt-2 text-xs leading-5 text-ink-2">이 결과의 위치 근거를 연결하지 못해 지도에는 그리지 않습니다. 계산 격자 보기는 유지됩니다.</p>}
  </div>;
}

export function AnalysisCoverage({ detail }: { detail: AnalysisView }) {
  if (!detail.result || detail.executionState !== "COMPLETED" || !["PROVISIONAL_ACCURACY_UNVERIFIED", "EVALUATED"].includes(detail.suitabilityState)) {
    return <p className="mt-2 text-xs leading-5 text-ink-2">현재 제공할 수 있는 계산 범위 근거가 없습니다. 자료 없음이나 0으로 해석하지 마세요.</p>;
  }
  if (!coverageFitsDisplay(detail.result.coverage.rows, detail.result.coverage.columns)) {
    return <p className="mt-2 text-xs leading-5 text-ink-2">계산 격자가 화면 표시 한도를 넘었습니다. 수치·근거 기록은 별도로 유지되며 빈 영역으로 바꾸지 않습니다.</p>;
  }
  return <CoverageReader key={[detail.siteId, detail.analysisId, detail.result.reportDigest,
    detail.result.coverage.coverageWitnessDigest, detail.evidenceDigest].join(":")} detail={detail} />;
}
