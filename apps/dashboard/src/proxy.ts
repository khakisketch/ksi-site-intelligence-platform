import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { PATHNAME_HEADER, SESSION_COOKIE_NAME } from "@/lib/core-api/session-cookie";
import { AUTH_SESSION_COOKIE_NAME } from "@/lib/auth/auth-cookie";

// Next.js 16: middleware.ts → proxy.ts 로 개명(node_modules/next/dist/docs 확인).
//
// 이건 낙관적 체크일 뿐이다(쿠키 존재만 확인 — 토큰 유효성은 Core 가 매 요청 검증).
// Route Handler·Server Component 는 이 proxy 를 신뢰하지 않고 각자 세션을 다시
// 확인한다(Next 공식 문서: "Always verify authentication ... rather than relying
// on Proxy alone" — matcher 변경이 조용히 보호를 없앨 수 있어서다).
// `/field`도 일반 Operations Console 보호 경로다. Pilot 2 웹뷰 진입점은 없다.
const PUBLIC_PATHS = ["/login"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

function isUnavailableHilPath(pathname: string): boolean {
  const isHilPath = pathname === "/hil" || pathname.startsWith("/hil/");
  return (
    isHilPath &&
    (process.env.NODE_ENV === "production" ||
      process.env.KSI_DASHBOARD_HIL_TOOLS_ENABLED !== "1")
  );
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies
    .getAll()
    .some(
      (cookie) =>
        cookie.name === SESSION_COOKIE_NAME ||
        cookie.name === AUTH_SESSION_COOKIE_NAME ||
        cookie.name.startsWith(`${AUTH_SESSION_COOKIE_NAME}.`),
    );

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(PATHNAME_HEADER, pathname);
  const withPathnameHeader = () => NextResponse.next({ request: { headers: requestHeaders } });

  // /api/* 는 리다이렉트하지 않는다 — 클라이언트가 fetch()로 JSON 응답을 기대하는데
  // 여기서 /login(HTML, 200)으로 리다이렉트하면 response.ok 가 참이 되어 "인증 안 됨"이
  // "성공"으로 오인될 수 있다. Route Handler 가 세션을 직접 검증해 401 JSON을 낸다.
  if (pathname.startsWith("/api/")) {
    return withPathnameHeader();
  }

  // 비활성 HIL 경로는 인증 화면으로 존재를 암시하지 않고 실제 route의 404로 보낸다.
  // 개발에서 명시 flag를 켠 경우에만 아래 일반 세션 보호를 그대로 받는다.
  if (isUnavailableHilPath(pathname)) {
    return new NextResponse(null, {
      status: 404,
      headers: { "Cache-Control": "private, no-store" },
    });
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
