export interface SiteListParams {
  q?: string;
  status?: string;
  sort?: string;
  group?: string;
  page?: string;
}

const KEYS = ["q", "status", "sort", "group", "page"] as const;

/** 데스크톱 보기 방식별 한 페이지 행 수 — 카드 4 / 목록 10. */
export const SITE_LIST_CARDS_PER_PAGE = 4;
export const SITE_LIST_LIST_PER_PAGE = 10;

/**
 * 현장 목록 URL 생성 — 링크를 유지한 채 한 파라미터만 바꾼다.
 * 칩을 눌러도 검색어·정렬을 잃지 않고, 정렬을 바꿔도 입력 중 검색어를 잃지 않는다.
 * 빈 값은 파라미터에서 뺀다 — `q=` 같은 빈 조건을 URL에 남기지 않는다.
 * 검색·필터·정렬 이동은 page 를 붙이지 않으므로 1페이지로 돌아간다.
 */
export function buildSiteListHref(
  base: SiteListParams,
  patch: Partial<Record<(typeof KEYS)[number], string | undefined>>,
): string {
  const merged = { ...base, ...patch };
  // 서버 링크의 base에는 현재 page가 함께 들어올 수 있다. 기준을 바꾸는
  // 이동은 page를 명시한 pager와 달리 항상 첫 페이지에서 시작한다.
  const changesCriteria = ["q", "status", "sort", "group"].some((key) =>
    Object.prototype.hasOwnProperty.call(patch, key),
  );
  if (changesCriteria && !Object.prototype.hasOwnProperty.call(patch, "page")) {
    merged.page = undefined;
  }
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

/** page 파라미터 읽기 — 없거나 깨졌거나 1 미만이면 1페이지다. */
export function normalizePageParam(value: unknown): number {
  const n = typeof value === "string" || typeof value === "number" ? Math.floor(Number(value)) : NaN;
  return Number.isFinite(n) && n >= 1 ? n : 1;
}

/** 범위를 벗어난 페이지는 끝 페이지로 당긴다 — 가짜 빈 결과를 만들지 않는다. */
export function clampPage(page: number, totalPages: number): number {
  return Math.min(Math.max(page, 1), Math.max(1, totalPages));
}

/** 데스크톱 한 페이지 분량만 잘라낸다 — 타일·합계는 이 바깥에서 다룬다. */
export function paginateRows<T>(rows: readonly T[], page: number, perPage: number): T[] {
  const start = (page - 1) * perPage;
  return rows.slice(start, start + perPage);
}

/**
 * 페이지 번호 창 — 처음·마지막·현재±이웃만 보여주고 나머지는 줄인다.
 * 한 칸만 가려질 때는 숫자로 채운다(`1 2 3 4 … 50` 식).
 */
export function pageWindow(current: number, total: number): Array<number | "…"> {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const picked = [...new Set([1, total, current - 1, current, current + 1])]
    .filter((p) => p >= 1 && p <= total)
    .sort((a, b) => a - b);
  const windowed: Array<number | "…"> = [];
  let prev = 0;
  for (const p of picked) {
    if (p - prev === 2) windowed.push(prev + 1);
    else if (p - prev > 2) windowed.push("…");
    windowed.push(p);
    prev = p;
  }
  return windowed;
}

/**
 * 머리말 건수 — 걸린 범위와 전체를 함께 말한다.
 * 한 페이지에 다 들면 `5 / 5곳 표시`, 잘리면 `3–4 / 5곳 표시`.
 */
export function pageRangeMeta(filtered: number, total: number, page: number, perPage: number): string {
  if (filtered === 0) return `0 / ${total}곳 표시`;
  const start = (page - 1) * perPage + 1;
  const end = Math.min(page * perPage, filtered);
  // 한 페이지에 다 들 때만 `5 / 5곳 표시` 로 줄인다. 잘린 페이지는
  // 한 행만 남았어도 `5–5 / 5곳` 처럼 범위를 밝혀 `5곳 표시` 오독을 막는다.
  if (start === 1 && end === filtered) return `${filtered} / ${total}곳 표시`;
  return `${start}–${end} / ${total}곳 표시`;
}

/**
 * 보기 전환용: 현재 주소창 검색식에서 page만 뺀 이동先.
 * page가 없으면 null — 이동 자체가 필요 없다.
 */
export function dropSiteListPage(search: string): string | null {
  const params = new URLSearchParams(search);
  if (!params.has("page")) return null;
  params.delete("page");
  const rest = params.toString();
  return rest ? `/sites?${rest}` : "/sites";
}
