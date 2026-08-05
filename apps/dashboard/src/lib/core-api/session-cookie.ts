// 세션 쿠키 이름 SSOT — "server-only" 를 import하지 않는다(proxy.ts 는 Node 런타임에서
// NextRequest.cookies 로 존재만 확인하므로 이 상수만 필요, session.ts 는 실제 읽기/쓰기).
export const SESSION_COOKIE_NAME = "ksi_session_token";

// proxy.ts 가 매 요청에 실어 보내는 현재 경로 — TopBar 가 usePathname 없이
// "지금 /login 화면인가"를 판별하는 데 쓴다(무효 세션 탈출구 문구 중복 방지).
export const PATHNAME_HEADER = "x-pathname";
