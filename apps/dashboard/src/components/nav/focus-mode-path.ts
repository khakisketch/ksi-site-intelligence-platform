/**
 * 공간 작업환경 집중 모드(focus mode) 경로 판정 — SSR·클라이언트 공용.
 *
 * 집중 모드에서는 전역 232px 레일과 상단바 정상행을 접어 무대를 통째로
 * 쓴다. chromeless(/login)와는 다른 개념이다: 인증·권한·읽기 게이트는
 * 그대로 두고 배치만 바꾼다. 클라이언트 네비게이션 사이의 복원은 ShellLayoutMode 가 같은 술어로 맞춘다.
 *
 * 정확히 세 경로만 해당한다. 분석·로그인·중첩 하위 경로는 절대 끌어들이지
 * 않는다 — 세그먼트 경계까지 본다.
 *
 * - `/design-preview/materials` — 명시적 예시 경로.
 * - `/sites/[siteId]/spatial-assets` — 실제 등록 자료 무대.
 * - `/sites/[siteId]` — 실제 작업공간 단일/비교/결과 무대. 쿼리(mode 등)는
 *   pathname에 없으므로 그대로 둔다. `/sites/new` 충돌을 피하려고 세그먼트가
 *   `new`이면 제외한다.
 */
export function isFocusModePath(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  if (pathname === "/design-preview/materials" || pathname === "/design-preview/materials/") {
    return true;
  }
  if (/^\/sites\/[^/]+\/spatial-assets\/?$/.test(pathname)) {
    return true;
  }
  const exact = /^\/sites\/([^/]+)\/?$/.exec(pathname);
  if (exact) {
    // `/sites/new`은 현장 등록 경로이므로 집중 모드가 아니다.
    if (exact[1] === "new") return false;
    return true;
  }
  return false;
}
