import Link from "next/link";

/**
 * 현장 시작 요약 — 공간 확인 작업공간 아래 두는 한 줄 요약.
 *
 * 실제 공간 작업공간이 검증된 선택을 이미 갖고 그 자리에서 다음 행동을
 * 안내할 때는 건수만 둔다(중복 CTA·다음 문단 없음). 비어 있거나 조회
 * 실패(unknown)일 때는 다음 행동 안내를 그대로 둔다. 건수 문구·목적지·
 * "확인 불가" 규율은 그대로 유지한다.
 */
export function SiteStartGuidance({
  siteId,
  workAreaCount,
  observationWorkOrderCount,
  externalResultCount,
  hasMoreExternalResults,
  hasWorkspaceActions = false,
}: {
  siteId: string;
  workAreaCount: number | null;
  observationWorkOrderCount: number | null;
  externalResultCount: number | null;
  hasMoreExternalResults: boolean | null;
  /** 실제 공간 작업공간 선택이 있어 그 자리가 다음 행동을 안내할 때만 true. */
  hasWorkspaceActions?: boolean;
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
          : "촬영 시점을 골라 기준 자료와 비교할 자료를 확인하세요. 비교 가능 여부는 요청할 때 확인합니다.";
  const nextStepAction = workAreaCount === null || workAreaCount === 0
    ? { href: `${sitePath}/work-areas`, label: "작업구역 확인" }
    : observationWorkOrderCount === null || observationWorkOrderCount === 0
      ? { href: `${sitePath}?section=work-orders`, label: "관측 작업 현황 확인" }
      : { href: `${sitePath}/analysis`, label: "비교할 자료 선택" };

  return <section className="rounded-lg border border-line bg-surface px-4 py-2.5" aria-label="현장 시작 안내">
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
      <p><span className="text-ink-muted">작업구역 </span><span className="font-semibold">{areaStatus}</span></p>
      <p><span className="text-ink-muted">관측 작업 </span><span className="font-semibold">{workOrderStatus}</span></p>
      {externalResultCount !== 0 && <p><span className="text-ink-muted">외부 비교 기록 </span><span className="font-semibold">{resultStatus}</span></p>}
      {!hasWorkspaceActions && <Link href={nextStepAction.href} className="btn ml-auto">{nextStepAction.label}</Link>}
    </div>
    {!hasWorkspaceActions && <p className="mt-1.5 text-[12px] leading-5 text-ink-2"><span className="font-semibold">다음 확인 · </span>{nextStep}</p>}
  </section>;
}
