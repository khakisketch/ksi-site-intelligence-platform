// 앱 셸(사이드바·상단바·하단탭)을 통째로 벗는 경로 — 단일 판정.
//
// 이 판정이 layout.tsx 안에 `pathname === "/login"` 로 박혀 있었고, 같은 판정이
// DesktopSidebar·MobileBottomNav 에도 각각 복제돼 있었다. 세 곳이 각자 판정하는
// 구조에서는 새 chromeless 경로를 하나 추가할 때 한 곳을 빠뜨리면 **그 화면만**
// 반쪽 셸을 얻는다(레일은 사라졌는데 그리드 트랙은 남는 식). 그래서 술어를 하나로
// 모은다.
//
// ── /field 가 여기 들어가는 이유 ────────────────────────────────────────────
// 조종기(DJI RC Plus / Pilot 2 웹뷰)는 화면이 **가로**다. CSS 픽셀 폭이 lg(1024) 이상으로
// 보고될 가능성이 크고, 그 순간 layout 의 `lg:grid lg:grid-cols-[176px_1fr]` 가 켜진다.
// 결과는 두 가지 동시 결함이다:
//   ① 좁은 물리 화면의 176px 을 사이드바가 먹는다 — 현장에서 쓸 일이 없는 레일이다.
//   ② `lg:h-screen lg:overflow-hidden` + `main` 만 스크롤 = **중첩 스크롤러**가 된다.
// 장갑 낀 손으로 중첩 스크롤러를 다루는 건 실패한다 — 바깥을 잡으면 안 움직이고
// 안을 잡으면 관성이 다르게 걸린다. /field 는 문서 흐름 + 단일 스크롤이어야 한다.
//
// 실측 CSS 폭은 FIELD-0b U9 에서 재기 전까지 **모른다**. 모르는 값에 레이아웃을
// 걸지 않고 경로로 끊는 이유다.
const CHROMELESS_PREFIXES = ["/login", "/field"] as const;

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
