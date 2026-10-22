import Link from "next/link";

/**
 * 선택 구역의 다음 행동 — 탐색 첫 화면과 구역 상세 화면이 같은 것을 본다.
 *
 * 한 곳에만 있으면 화면마다 다른 행동을 제안하게 된다. 그래서 링크·라벨·
 * 보조 행동을 한 번만 계산해(호출자가 같은 값을 넘긴다) 두 자리가 그대로
 * 공유한다. 여기에는 사실이 아니라 '무엇을 할 수 있는가'만 둔다 — 개수·
 * 식별자·정확도 같은 기술 사실은 각 화면의 펼침이 맡는다.
 */
export interface SiteAreaNextAction {
  /** 주 행동 — 이 화면에서 한 가지로 가장 먼저 할 수 있는 일. */
  primary: { href: string; label: string };
  /** 보조 등록 진입 — 주 행동과 같은 목적이면 비운다. */
  secondaryRegisterHref: string | null;
  /** 변화량 분석 시작 진입 — 권한이 없으면 비운다. */
  secondaryCompareHref: string | null;
}

/**
 * 선택 구역의 다음 행동을 계산한다 — 탐색 첫 화면과 구역 상세 화면이 같은
 * 것을 본다. 어느 화면이든 같은 구역에서 같은 행동을 제안해야 한다.
 *
 * - 주 행동은 이 구역의 최근 분석이 있으면 그 기록으로, 없으면 등록(가능
 *   할 때) 또는 분석 목록으로 간다. 구역·권한·분석 사실을 새로 만들어내지
 *   않고 이미 읽은 값만 쓴다.
 * - 보조 등록은 주 행동과 같은 목적이면 숨긴다(같은 일을 두 번 제안하지
 *   않는다). 비교 진입은 권한이 있는 활성 구역에만 단다.
 */
export function resolveSiteAreaNextAction(input: {
  sitePath: string;
  workAreaId: string;
  workAreaStatus: "ACTIVE" | "ARCHIVED";
  canCreateWorkOrder: boolean;
  canCreateAnalysis: boolean;
  latestAnalysis: { workAreaId: string; analysisId: string } | null;
  /** 정식 쌍의 인계 쿼리(힌트 6건 + 복귀 참조 2건) — 분석 이동에만 덧붙인다. */
  pairQuery?: string | null;
}): SiteAreaNextAction {
  const { sitePath, workAreaId, workAreaStatus, canCreateWorkOrder, canCreateAnalysis, latestAnalysis, pairQuery } = input;
  const active = workAreaStatus === "ACTIVE";
  const withPair = (href: string): string => {
    if (!pairQuery) return href;
    const hashIndex = href.indexOf("#");
    const base = hashIndex >= 0 ? href.slice(0, hashIndex) : href;
    const hash = hashIndex >= 0 ? href.slice(hashIndex) : "";
    const separator = base.includes("?") ? "&" : "?";
    return `${base}${separator}${pairQuery}${hash}`;
  };
  const scopedRegisterHref = `${sitePath}/observations/new?workAreaId=${encodeURIComponent(workAreaId)}`;
  const scopedCompareHref = withPair(`${sitePath}/analysis?workAreaId=${encodeURIComponent(workAreaId)}#new-analysis-request`);
  const scopedAnalysisListHref = withPair(active
    ? `${sitePath}/analysis?workAreaId=${encodeURIComponent(workAreaId)}`
    : `${sitePath}/analysis`);
  const canRegisterHere = canCreateWorkOrder && active;
  const canCompareHere = canCreateAnalysis && active;
  const primary = latestAnalysis
    ? {
      href: withPair(`${sitePath}/analysis?workAreaId=${encodeURIComponent(latestAnalysis.workAreaId)}&analysisId=${encodeURIComponent(latestAnalysis.analysisId)}`),
      label: "이 구역의 최근 분석 확인",
    }
    : {
      href: canRegisterHere ? scopedRegisterHref : scopedAnalysisListHref,
      label: canRegisterHere ? "관측 자료 등록" : "변화 분석 보기",
    };
  return {
    primary,
    secondaryRegisterHref: canRegisterHere && primary.href !== scopedRegisterHref ? scopedRegisterHref : null,
    secondaryCompareHref: canCompareHere ? scopedCompareHref : null,
  };
}

export function SiteAreaNextActionNav({
  sitePath,
  workAreaId,
  action,
  archived,
  canRegisterOrCompare,
  label = "선택 구역 다음 확인",
  compact = false,
}: {
  sitePath: string;
  workAreaId: string;
  action: SiteAreaNextAction;
  /** 보관된 구역 안내 — 새 등록·비교가 불가능하다는 사실을 밝힌다. */
  archived: boolean;
  /** 등록·비교가 가능한 구역인지 — 그때만 진행 방법을 한 줄로 말한다. */
  canRegisterOrCompare: boolean;
  /** 접근성 이름 — 같은 행동을 두 자리에 둘 때는 자리를 구분한다. */
  label?: string;
  /**
   * 첫 화면용 짧은 형태 — 주 행동 하나만 먼저 보이고, 다른 진입은
   * '다른 보기' 펼침에 둔다. 처음 보는 사람이 다섯 개의 단추를 먼저
   * 훑어야 하는 상황을 만든다.
   */
  compact?: boolean;
}) {
  if (compact) {
    return (
      <nav className="flex flex-col gap-1.5" aria-label={label}>
        <Link href={action.primary.href} className="btn btn-primary w-fit">
          {action.primary.label}
        </Link>
        <details className="text-[12px] text-ink-2">
          <summary className="tap-target cursor-pointer font-semibold">다른 보기</summary>
          <div className="mt-1.5 flex flex-col gap-2">
            {(action.secondaryRegisterHref || action.secondaryCompareHref) && (
              <p className="flex flex-wrap gap-2">
                {action.secondaryRegisterHref && (
                  <Link href={action.secondaryRegisterHref} className="btn w-fit">
                    이 구역 자료 등록
                  </Link>
                )}
                {action.secondaryCompareHref && (
                  <Link href={action.secondaryCompareHref} className="btn w-fit">
                    변화량 분석
                  </Link>
                )}
              </p>
            )}
            <p className="flex flex-wrap gap-x-3 text-[12px]">
              <Link
                href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(workAreaId)}`}
                className="tap-target underline"
              >
                등록 자료 보기
              </Link>
              <Link href={`${sitePath}/observations`} className="tap-target underline">
                외부 비교 기록
              </Link>
            </p>
            {canRegisterOrCompare && (
              <p className="text-[11.5px] leading-5 text-ink-muted">
                자료 등록 뒤에는 파일 제출·검사를 같은 작업 화면에서 이어갑니다. 비교는 기준·현재 두 시점을 고른 뒤 요청합니다.
              </p>
            )}
          </div>
        </details>
        {archived && (
          <p className="text-[12px] text-ink-2">
            보관된 구역입니다. 기존 자료와 결과를 확인할 수 있으며, 새 자료 등록과 비교는 활성 구역에서 시작하세요.
          </p>
        )}
      </nav>
    );
  }
  return (
    <nav className="flex flex-col gap-2" aria-label={label}>
      <Link href={action.primary.href} className="btn btn-primary w-fit">
        {action.primary.label}
      </Link>
      {(action.secondaryRegisterHref || action.secondaryCompareHref) && (
        <p className="flex flex-wrap gap-2">
          {action.secondaryRegisterHref && (
            <Link href={action.secondaryRegisterHref} className="btn w-fit">
              이 구역 자료 등록
            </Link>
          )}
          {action.secondaryCompareHref && (
            <Link href={action.secondaryCompareHref} className="btn w-fit">
              변화량 분석
            </Link>
          )}
        </p>
      )}
      <p className="flex flex-wrap gap-x-3 text-[12px]">
        <Link
          href={`${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(workAreaId)}`}
          className="tap-target underline"
        >
          등록 자료 보기
        </Link>
        <Link href={`${sitePath}/observations`} className="tap-target underline">
          외부 비교 기록
        </Link>
      </p>
      {canRegisterOrCompare && (
        <p className="text-[11.5px] leading-5 text-ink-muted">
          자료 등록 뒤에는 파일 제출·검사를 같은 작업 화면에서 이어갑니다. 비교는 기준·현재 두 시점을 고른 뒤 요청합니다.
        </p>
      )}
      {archived && (
        <p className="text-[12px] text-ink-2">
          보관된 구역입니다. 기존 자료와 결과를 확인할 수 있으며, 새 자료 등록과 비교는 활성 구역에서 시작하세요.
        </p>
      )}
    </nav>
  );
}
