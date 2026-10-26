import Link from "next/link";

export function AnalysisStartGuide({
  siteId,
  workAreaCount,
  observationCount,
  analysisCount,
  hasMoreAnalyses,
  canCreate,
  workAreaId,
  /**
   * 후보·구역이 있어 실제 선택이 먼저일 때 true — 안내는 접힌 도움말로
   * 둔다. 기록·후보가 없어 다음 행동을 정해야 할 때는 펼친 안내를 둔다.
   */
  compact = false,
}: {
  siteId: string;
  workAreaCount: number;
  observationCount: number;
  analysisCount: number;
  hasMoreAnalyses: boolean;
  canCreate: boolean;
  workAreaId?: string | null;
  compact?: boolean;
}) {
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const canChoosePair = workAreaCount > 0 && observationCount >= 2;

  const body = (<>
    <ol className="grid gap-3 border-t border-line pt-3 sm:grid-cols-3">
      <li className="min-w-0">
        <p className="text-[11.5px] font-semibold text-ink-muted">1 · 작업구역</p>
        <p className="mt-1 text-[13px] font-semibold">{workAreaCount > 0 ? `${workAreaCount}개 확인됨` : "등록된 작업구역 없음"}</p>
        <Link className="mt-2 inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline" href={`${sitePath}/work-areas`}>작업구역 현황 확인</Link>
      </li>
      <li className="min-w-0">
        <p className="text-[11.5px] font-semibold text-ink-muted">2 · 관측 후보</p>
        <p className="mt-1 text-[13px] font-semibold">{observationCount > 0 ? `${observationCount}개 표시됨` : "표시된 후보 없음"}</p>
        <p className="mt-1 text-[11.5px] leading-4 text-ink-2">구분 기준과 등록 버전·관측 기록 표시는 아래 새 변화 분석 요청에 있습니다. 이 목록은 작업구역 적합성을 미리 판정하지 않습니다.</p>
        {observationCount < 2 && <>
          <p className="mt-1 text-[11.5px] leading-5 text-ink-2">파일을 등록한 사실과 비교 후보 표시는 다릅니다. 촬영 날짜만 있거나 시각이 미상인 자료는 현재 시점 비교 후보에 포함되지 않습니다. 등록 자료에서 입력 정보와 검사 상태를 확인하세요.</p>
          <Link className="mt-1 inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline" href={`${sitePath}/spatial-assets${workAreaId ? `?workAreaId=${encodeURIComponent(workAreaId)}` : ""}`}>등록 자료·촬영 정보 확인</Link>
        </>}
      </li>
      <li className="min-w-0">
        <p className="text-[11.5px] font-semibold text-ink-muted">3 · 변화 분석 기록</p>
        <p className="mt-1 text-[13px] font-semibold">{analysisCount > 0 ? `${analysisCount}개 표시됨` : "표시된 기록 없음"}</p>
        <p className="mt-1 text-[11.5px] leading-4 text-ink-2">{hasMoreAnalyses ? "최근 페이지의 일부 기록입니다. 아래에서 이전 변화 분석을 더 불러올 수 있습니다." : "표시된 목록 범위에서 확인된 기록입니다."}</p>
      </li>
    </ol>

    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
      <p className="max-w-3xl text-[12px] leading-5 text-ink-2">
        {canChoosePair
          ? canCreate
            ? "서로 다른 기준·현재 관측을 선택하면 Core가 권한·자료·적합성을 확인합니다. 등록은 검증이나 정량 사용 가능 판정이 아닙니다."
            : "관측 후보가 있어도 새 변화 분석 요청은 권한 있는 현장 담당자가 진행해야 합니다. 등록은 검증이나 정량 사용 가능 판정이 아닙니다."
          : workAreaCount === 0
            ? "먼저 작업구역 현황을 확인하세요. 새 구역 설정은 권한이 있는 담당자가 진행해야 할 수 있습니다."
            : "변화 분석 요청에는 서로 다른 관측 두 개와 작업구역이 필요합니다. 필요한 등록·보완은 관측 담당자와 확인하세요. 후보 수는 적합성 판정이 아닙니다."}
      </p>
      {canChoosePair && canCreate && <Link href="#new-analysis-request" className="btn btn-primary shrink-0">변화 분석 요청으로 이동</Link>}
    </div>
  </>);

  if (compact) {
    return <details className="rounded-lg border border-line bg-surface px-4 py-3">
      <summary className="tap-target cursor-pointer text-[14px] font-bold">변화 분석 시작 안내</summary>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">현재 이 현장에서 확인되는 기록을 바탕으로 다음 단계를 안내합니다. 기록 수만으로 분석 적합성이나 정확도를 판정하지 않습니다.</p>
      <div className="mt-3">{body}</div>
    </details>;
  }

  return <section className="rounded-lg border border-line bg-surface p-4" aria-labelledby="analysis-start-heading">
    <header>
      <h2 id="analysis-start-heading" className="text-[15px] font-bold">변화 분석 시작 안내</h2>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">현재 이 현장에서 확인되는 기록을 바탕으로 다음 단계를 안내합니다. 기록 수만으로 분석 적합성이나 정확도를 판정하지 않습니다.</p>
    </header>

    <div className="mt-3">{body}</div>
  </section>;
}
