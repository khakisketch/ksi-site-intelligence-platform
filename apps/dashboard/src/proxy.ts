import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { PATHNAME_HEADER, SESSION_COOKIE_NAME } from "@/lib/core-api/session-cookie";

// Next.js 16: middleware.ts → proxy.ts 로 개명(node_modules/next/dist/docs 확인).
//
// 이건 낙관적 체크일 뿐이다(쿠키 존재만 확인 — 토큰 유효성은 Core 가 매 요청 검증).
// Route Handler·Server Component 는 이 proxy 를 신뢰하지 않고 각자 세션을 다시
// 확인한다(Next 공식 문서: "Always verify authentication ... rather than relying
// on Proxy alone" — matcher 변경이 조용히 보호를 없앨 수 있어서다).
// ── /field 가 여기 있는 이유 ────────────────────────────────────────────────
// Pilot 2 서드파티 클라우드 웹뷰가 302 를 그대로 따라가 준다는 보장이 우리에겐 없다
// (FIELD-0b U9 에서 실측하기 전까지 **모른다**). 리다이렉트를 삼키는 웹뷰에서는
// 세션이 없을 때 화면이 그냥 빈 채로 멈추고, 현장에서 그건 "앱이 죽었다"로 읽힌다.
// 그래서 /field 는 리다이렉트 대상에서 빼고, 화면이 직접 인라인 로그인 폼을 그린다.
//
// 이건 화면을 여는 것이지 데이터를 여는 게 아니다 — /field 의 서버 컴포넌트는
// 다른 화면과 똑같이 세션을 다시 확인하고, 세션이 없으면 Core 를 아예 부르지 않는다.
const PUBLIC_PATHS = ["/login", "/field"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE_NAME);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(PATHNAME_HEADER, pathname);
  const withPathnameHeader = () => NextResponse.next({ request: { headers: requestHeaders } });

  // /api/* 는 리다이렉트하지 않는다 — 클라이언트가 fetch()로 JSON 응답을 기대하는데
  // 여기서 /login(HTML, 200)으로 리다이렉트하면 response.ok 가 참이 되어 "인증 안 됨"이
  // "성공"으로 오인될 수 있다. Route Handler 가 세션을 직접 검증해 401 JSON을 낸다.
  if (pathname.startsWith("/api/")) {
    return withPathnameHeader();
  }

  if (!hasSession && !isPublicPath(pathname)) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname + request.nextUrl.search);
    return NextResponse.redirect(loginUrl);
  }

  // 쿠키가 "있다"고 로그인 화면을 막지 않는다 — 쿠키는 존재만 확인했을 뿐 유효성은
  // 모른다(위 주석 참조). 무효/만료 토큰을 쥔 사용자가 /login 에 못 들어가면 앱을
  // 벗어날 방법이 없는 데드락이 된다(독립 재검토 P1-A). "이미 로그인됨" 편의성보다
  // 항상 재로그인 가능함을 우선한다 — 이미 유효한 세션이면 로그인 폼을 다시 봐도
  // 손해가 없다.
  return withPathnameHeader();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
