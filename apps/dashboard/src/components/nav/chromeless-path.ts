// 앱 셸(사이드바·상단바·하단탭)을 통째로 벗는 경로 — 단일 판정.
//
// 이 판정이 layout.tsx 안에 `pathname === "/login"` 로 박혀 있었고, 같은 판정이
// DesktopSidebar·MobileBottomNav 에도 각각 복제돼 있었다. 세 곳이 각자 판정하는
// 구조에서는 새 chromeless 경로를 하나 추가할 때 한 곳을 빠뜨리면 **그 화면만**
// 반쪽 셸을 얻는다(레일은 사라졌는데 그리드 트랙은 남는 식). 그래서 술어를 하나로
// 모은다.
//
// `/field`는 ADR-KSI-024부터 일반 Operations Console 셸을 사용한다. RC/Pilot 2에는
// KSI 업무 UI를 열지 않으므로 장비 화면 크기를 이유로 셸을 벗기는 예외가 없다.
const CHROMELESS_PREFIXES = ["/login"] as const;

/**
 * 이 경로가 앱 셸 없이 그려지는가.
 *
 * 접두 일치는 세그먼트 경계까지 본다 — `/fieldwork` 같은 미래 경로가 `/field` 의
 * 접두라는 이유만으로 조용히 셸을 잃으면 안 된다.
 */
export function isChromelessPath(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return CHROMELESS_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
