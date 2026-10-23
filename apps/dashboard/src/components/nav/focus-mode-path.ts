/**
 * 공간 작업환경 집중 모드(focus mode) 경로 판정 — SSR·클라이언트 공용.
 *
 * 집중 모드에서는 전역 232px 레일과 상단바 정상행을 접어 무대를 통째로
 * 쓴다. chromeless(/login)와는 다른 개념이다: 인증·권한·읽기 게이트는
 * 그대로 두고 배치만 바꾼다.
 *
 * 정확히 두 경로만 해당한다. 분석·로그인·중첩 하위 경로는 절대 끌어들이지
 * 않는다 — 세그먼트 경계까지 본다.
 */
export function isFocusModePath(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  if (pathname === "/design-preview/materials" || pathname === "/design-preview/materials/") {
    return true;
  }
  return /^\/sites\/[^/]+\/spatial-assets\/?$/.test(pathname);
}
