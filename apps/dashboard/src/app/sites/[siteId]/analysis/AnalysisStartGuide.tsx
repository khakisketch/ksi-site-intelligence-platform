import Link from "next/link";

export function AnalysisStartGuide({
  siteId,
  workAreaCount,
  observationCount,
  analysisCount,
  hasMoreAnalyses,
  canCreate,
}: {
  siteId: string;
  workAreaCount: number;
  observationCount: number;
  analysisCount: number;
  hasMoreAnalyses: boolean;
  canCreate: boolean;
}) {
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const canChoosePair = workAreaCount > 0 && observationCount >= 2;

  return <section className="rounded-lg border border-line bg-surface p-4" aria-labelledby="analysis-start-heading">
    <header>
      <h2 id="analysis-start-heading" className="text-[15px] font-bold">변화 분석 시작 안내</h2>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">현재 이 현장에서 확인되는 기록을 바탕으로 다음 단계를 안내합니다. 기록 수만으로 분석 적합성이나 정확도를 판정하지 않습니다.</p>
    </header>

    <ol className="mt-3 grid gap-3 border-t border-line pt-3 sm:grid-cols-3">
      <li className="min-w-0">
        <p className="text-[11.5px] font-semibold text-ink-muted">1 · 작업구역</p>
        <p className="mt-1 text-[13px] font-semibold">{workAreaCount > 0 ? `${workAreaCount}개 확인됨` : "등록된 작업구역 없음"}</p>
        <Link className="mt-2 inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline" href={`${sitePath}/work-areas`}>작업구역 현황 확인</Link>
      </li>
      <li className="min-w-0">
        <p className="text-[11.5px] font-semibold text-ink-muted">2 · 관측 후보</p>
        <p className="mt-1 text-[13px] font-semibold">{observationCount > 0 ? `${observationCount}개 표시됨` : "표시된 후보 없음"}</p>
        <p className="mt-1 text-[11.5px] leading-4 text-ink-2">구분 기준과 등록 버전·관측 기록 표시는 아래 새 변화 분석 요청에 있습니다. 이 목록은 작업구역 적합성을 미리 판정하지 않습니다.</p>
        {observationCount < 2 && <Link className="mt-1 inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline" href={`${sitePath}/observations`}>외부 비교 기록 확인</Link>}
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
  </section>;
}
