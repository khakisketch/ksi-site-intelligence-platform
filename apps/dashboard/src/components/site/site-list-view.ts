/**
 * 현장 목록 데스크톱 보기 방식 — `cards`(2열 비주얼 카드) 또는 `list`(밀도 표).
 *
 * URL 쿼리에는 넣지 않는다. 보기 방식은 표현 취향이라 공유·뒤로가기·서버
 * 캐시의 대상이 아니다 — 기능 쿠키 하나에 기억하고 서버가 첫 렌더에 읽는다.
 * 쿠키에는 보기 값만 두고 ID·검색어·분석·권한·추적값을 절대 넣지 않는다.
 *
 * 기본값은 실제 준비된 출력 미리보기가 있는 비주얼 카드다(현장 진입의 시각
 * 인식). 명시적 목록 선택은 쿠키로 유지된다.
 */

export type SiteListViewMode = "cards" | "list";

export const SITE_LIST_VIEW_COOKIE = "ksi-sites-view";

export const SITE_LIST_VIEW_DEFAULT: SiteListViewMode = "cards";

const SITE_LIST_VIEW_MAX_AGE = 31536000; // 1년(초)

/** 쿠키·SSR 초기값이 깨져도 카드를 보여준다 — 목록은 명시적 선택일 때만. */
export function parseSiteListView(value: unknown): SiteListViewMode {
  return value === "list" ? "list" : "cards";
}

/** `document.cookie = ...` 에 바로 넣을 수 있는 한 줄. Path는 /sites 로 좁힌다. */
export function siteListViewCookieHeader(value: SiteListViewMode, secure: boolean): string {
  return (
    `${SITE_LIST_VIEW_COOKIE}=${value}` +
    "; Path=/sites" +
    `; Max-Age=${SITE_LIST_VIEW_MAX_AGE}` +
    "; SameSite=Lax" +
    (secure ? "; Secure" : "")
  );
}

function readCookieValue(cookieHeader: string): string | null {
  const prefix = `${SITE_LIST_VIEW_COOKIE}=`;
  const found = cookieHeader
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return found ? found.slice(prefix.length) : null;
}

/** 저장된 선택. 없거나 깨졌거나 읽기가 막히면 null — 호출부가 기본값으로 렌더한다. */
export function readSiteListViewCookie(
  doc: { cookie: string } = typeof document === "undefined" ? { cookie: "" } : document,
): SiteListViewMode | null {
  try {
    const raw = readCookieValue(doc.cookie);
    return raw === null ? null : parseSiteListView(raw) === raw ? (raw as SiteListViewMode) : null;
  } catch {
    // 읽기 차단(blocked cookie)은 기본값으로 — 쓰기와 같은 관대 정책.
    return null;
  }
}

/**
 * 현재 탭 선택을 기억한다. 저장소가 막혀도 throw 하지 않는다 —
 * 토글 자체는 로컬 상태라 그대로 동작한다.
 */
export function writeSiteListViewCookie(value: SiteListViewMode): void {
  try {
    document.cookie = siteListViewCookieHeader(
      value,
      typeof window !== "undefined" && window.location.protocol === "https:",
    );
  } catch {
    // 저장 차단(blocked cookie)은 무시한다 — 현재 탭 보기는 유지된다.
  }
}
