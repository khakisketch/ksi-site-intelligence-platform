import Link from "next/link";

export function SiteStartGuidance({
  siteId,
  workAreaCount,
  observationWorkOrderCount,
  externalResultCount,
  hasMoreExternalResults,
}: {
  siteId: string;
  workAreaCount: number | null;
  observationWorkOrderCount: number | null;
  externalResultCount: number | null;
  hasMoreExternalResults: boolean | null;
}) {
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const areaStatus = workAreaCount === null ? "확인 불가" : `${workAreaCount}개 목록됨`;
  const workOrderStatus = observationWorkOrderCount === null ? "확인 불가" : `${observationWorkOrderCount}개 목록됨`;
  const resultStatus = externalResultCount === null
    ? "확인 불가"
    : hasMoreExternalResults === true
      ? `최근 페이지 ${externalResultCount}개 · 더 있음`
      : hasMoreExternalResults === false
        ? `${externalResultCount}개 목록됨`
        : `${externalResultCount}개 표시됨 · 이어서 조회 여부 확인 불가`;

  const nextStep = workAreaCount === null
    ? "작업구역 목록을 확인할 수 없습니다. 상태를 빈 목록으로 간주하지 말고 담당자와 확인하세요."
    : workAreaCount === 0
      ? "현재 조회된 작업구역이 없습니다. 분석 전에 권한 있는 현장 담당자와 구역 설정 여부를 확인하세요."
      : observationWorkOrderCount === null
        ? "관측 작업 상태를 확인할 수 없습니다. 작업 현황을 확인한 뒤 분석 후보를 살펴보세요."
        : observationWorkOrderCount === 0
          ? "현재 조회된 관측 작업이 없습니다. 필요한 외부 관측은 자료 담당자와 확인하세요."
          : "분석 화면에서 실제 등록된 관측 후보를 촬영 시각·revision으로 확인하세요. Core가 요청 시 용도별 적합성을 판정합니다.";

  return <section className="rounded-lg border border-line bg-surface px-4 py-3" aria-label="현장 시작 안내">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-[14px] font-bold">이 현장에서 시작하기</h2>
        <p className="mt-1 max-w-3xl text-[12px] leading-5 text-ink-2">현재 조회된 기록을 기준으로 다음 확인 위치를 안내합니다. 등록·조회 상태는 검증·정확도 평가·분석 적합성을 뜻하지 않습니다.</p>
      </div>
      <Link href={`${sitePath}/analysis`} className="btn btn-primary shrink-0">분석 후보와 상태 확인</Link>
    </div>
    <dl className="mt-3 grid gap-x-4 gap-y-2 border-t border-line pt-3 text-[12px] sm:grid-cols-3">
      <div><dt className="text-ink-muted">작업구역</dt><dd className="mt-0.5 font-semibold">{areaStatus}</dd></div>
      <div><dt className="text-ink-muted">관측 작업</dt><dd className="mt-0.5 font-semibold">{workOrderStatus}</dd></div>
      <div><dt className="text-ink-muted">외부 결과 이력</dt><dd className="mt-0.5 font-semibold">{resultStatus}</dd></div>
    </dl>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
      <p className="max-w-3xl text-[12px] leading-5 text-ink-2"><span className="font-semibold">다음 확인 · </span>{nextStep}</p>
      {workAreaCount === null || workAreaCount === 0
        ? <Link href={`${sitePath}?section=spatial-assets`} className="inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline">공간 자산 현황 보기</Link>
        : observationWorkOrderCount === 0 || observationWorkOrderCount === null
          ? <Link href={`${sitePath}?section=work-orders`} className="inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline">관측 작업 현황 보기</Link>
          : null}
    </div>
  </section>;
}
