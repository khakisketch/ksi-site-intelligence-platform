export interface SiteListParams {
  q?: string;
  status?: string;
  sort?: string;
  group?: string;
}

const KEYS = ["q", "status", "sort", "group"] as const;

/**
 * 현장 목록 URL 생성 — 링크를 유지한 채 한 파라미터만 바꾼다.
 * 칩을 눌러도 검색어·정렬을 잃지 않고, 정렬을 바꿔도 입력 중 검색어를 잃지 않는다.
 * 빈 값은 파라미터에서 뺀다 — `q=` 같은 빈 조건을 URL에 남기지 않는다.
 */
export function buildSiteListHref(
  base: SiteListParams,
  patch: Partial<Record<(typeof KEYS)[number], string | undefined>>,
): string {
  const merged = { ...base, ...patch };
  const params = new URLSearchParams();
  for (const key of KEYS) {
    const value = merged[key];
    if (value) params.set(key, value);
  }
  const search = params.toString();
  return search ? `/sites?${search}` : "/sites";
}

/** 검색어만 지운다 — 상태·묶음·정렬은 그대로 둔다. */
export function clearSearchHref(base: SiteListParams): string {
  return buildSiteListHref(base, { q: undefined });
}
