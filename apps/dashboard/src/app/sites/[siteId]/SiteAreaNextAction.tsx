import { EXACT_ANALYSIS_HINT_QUERY_KEYS, VISUAL_PAIR_QUERY_KEYS } from "./site-visual-pair";

/**
 * 선택 구역의 다음 행동. 조회한 구역·권한·분석 기록으로 이동 주소를 정한다.
 */
export interface SiteAreaNextAction {
  /** 주 행동 — 이 화면에서 한 가지로 가장 먼저 할 수 있는 일. */
  primary: { href: string; label: string };
  /** 보조 등록 진입 — 주 행동과 같은 목적이면 비운다. */
  secondaryRegisterHref: string | null;
  /** 변화량 분석 시작 진입 — 권한이 없으면 비운다. */
  secondaryCompareHref: string | null;
  /** Related read-only materials route, with a validated pair when supplied. */
  materialsHref?: string;
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
  const withPair = (href: string, includeHints = true): string => {
    if (!pairQuery) return href;
    const target = new URL(href, "https://console.invalid");
    const pair = new URLSearchParams(pairQuery);
    const targetArea = target.searchParams.get("workAreaId");
    if (pair.getAll("workAreaId").length !== 1 || pair.get("workAreaId") !== workAreaId
      || (targetArea !== null && targetArea !== workAreaId)) return href;
    const keys = ["workAreaId", ...(includeHints ? Object.values(EXACT_ANALYSIS_HINT_QUERY_KEYS) : []), ...Object.values(VISUAL_PAIR_QUERY_KEYS)];
    if (keys.some((key) => pair.getAll(key).length > 1)) return href;
    for (const key of keys) {
      const value = pair.get(key);
      if (value !== null) target.searchParams.set(key, value);
    }
    if (!includeHints && target.searchParams.has("visualAAssetRef") && target.searchParams.has("visualBAssetRef")) {
      target.searchParams.set("mode", "compare");
    }
    return `${target.pathname}?${target.searchParams.toString()}${target.hash}`;
  };
  const scopedRegisterHref = `${sitePath}/observations/new?workAreaId=${encodeURIComponent(workAreaId)}`;
  const scopedCompareHref = withPair(`${sitePath}/analysis?workAreaId=${encodeURIComponent(workAreaId)}&request=new#new-analysis-request`);
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
    materialsHref: withPair(`${sitePath}?panel=materials&workAreaId=${encodeURIComponent(workAreaId)}`, false),
  };
}
