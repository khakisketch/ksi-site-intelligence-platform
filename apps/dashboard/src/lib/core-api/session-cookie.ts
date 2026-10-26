// 세션 쿠키 이름 SSOT — "server-only" 를 import하지 않는다(proxy.ts 는 Node 런타임에서
// NextRequest.cookies 로 존재만 확인하므로 이 상수만 필요, session.ts 는 실제 읽기/쓰기).
export const SESSION_COOKIE_NAME = "ksi_session_token";

// proxy.ts 가 매 요청에 실어 보내는 현재 경로 — TopBar 가 usePathname 없이
// "지금 /login 화면인가"를 판별하는 데 쓴다(무효 세션 탈출구 문구 중복 방지).
export const PATHNAME_HEADER = "x-pathname";

// 같은 요청의 쿼리 — 루트 레이아웃이 첫 렌더에서 viewer 셸 경로를 판정한다.
// `/sites/{id}?section=manage`와 `/sites/{id}`는 경로가 같으므로 경로만으로는
// 관리 화면에 viewer 셸을 적용하게 된다. 클라이언트 내비게이션은
// ShellLayoutMode가 useSearchParams로 같은 판정을 다시 한다.
export const SEARCH_HEADER = "x-search";

// 같은 요청의 복귀 주소(경로+쿼리) — 만료·거부 시 "다시 로그인"이 원래 화면으로
// 돌아오기 위해 쓴다. 쿼리까지 싣는 이유는 비교 쌍·선택 맥락을 잃지 않기
// 위해서다. 사용처는 반드시 safeNextPath 로 살균한다(외부·비정상 복귀 차단).
export const RETURN_TO_HEADER = "x-return-to";
