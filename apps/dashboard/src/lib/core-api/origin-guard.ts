import "server-only";

import type { NextRequest } from "next/server";

/**
 * 동일 출처가 아닌 mutating 요청인지 확인한다 — sameSite=lax 쿠키가 대부분의 cross-site
 * 요청을 막지만 `enctype="text/plain"` 폼 POST 등 일부 경로는 쿠키를 여전히 실어보낸다
 * (독립 재검토 1차 P2-F — 원래 risk 서술이 "인증/Origin 검사 없이"였는데 인증만 채웠던 공백).
 * Origin 헤더(대부분 브라우저가 실어보냄)를 우선 대조하고, 없으면 Sec-Fetch-Site 로
 * 폴백한다 — 둘 다 없으면(구형 브라우저·비브라우저 클라이언트) 거부하지 않는다(오탐
 * 방지 — 세션 검증이 이미 1차 방어선이라 여기는 defense-in-depth일 뿐이다).
 *
 * `request.nextUrl.origin` 을 기준으로 쓰지 않는다 — Next 가 이 값을 서버 기동 설정에서
 * 유도하며 `127.0.0.1` 을 `localhost` 로 강제 정규화한다(독립 재검토 2차 P2-F, 실측:
 * Host `127.0.0.1:3000` 요청에서 nextUrl.origin 이 `http://localhost:3000` 을 반환 —
 * 브라우저가 보내는 실제 Origin 과 구조적으로 어긋나 정상 same-origin 요청까지 403
 * 되는 회귀였다). 대신 요청 자신의 Host 헤더(리버스 프록시 뒤에서는
 * x-forwarded-host)와 Origin 의 host 만 비교한다 — Next Server Action 의 자체 CSRF
 * 검사(action-handler.js)가 쓰는 것과 동일한 기준이다.
 */
export function isCrossSiteMutation(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (origin === null) {
    const secFetchSite = request.headers.get("sec-fetch-site");
    if (secFetchSite !== null) {
      return secFetchSite !== "same-origin" && secFetchSite !== "none";
    }
    return false;
  }

  const forwardedHost = request.headers.get("x-forwarded-host")?.split(",")[0]?.trim();
  const host = forwardedHost || request.headers.get("host");
  if (host === null) return false;

  try {
    return new URL(origin).host !== host;
  } catch {
    // Origin 헤더가 존재하는데 파싱 불가 — 정상 브라우저는 만들지 않는 형태다.
    return true;
  }
}
