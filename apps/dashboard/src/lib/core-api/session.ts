import "server-only";

import { cookies } from "next/headers";

import { getDashboardAuthRuntime } from "@/lib/auth/runtime";

import { SESSION_COOKIE_NAME } from "./session-cookie";

// 로그인한 운영자의 Core bearer 토큰 원문을 httpOnly 쿠키에 그대로 담는다 — 대시보드
// 서버는 어차피 이 값을 Core Authorization 헤더에 그대로 전달해야 하므로 별도 암호화
// 계층은 이득이 없다(노출 표면은 브라우저 JS 가 아니라 브라우저↔대시보드서버 전송
// 구간뿐이며, httpOnly 가 이를 막는다). risk dashboard-unauthenticated-signing-proxy 해소.
export class MissingSessionError extends Error {
  constructor() {
    super("세션이 없습니다 — 다시 로그인하세요.");
    this.name = "MissingSessionError";
  }
}

export async function getSessionToken(): Promise<string> {
  const runtime = getDashboardAuthRuntime();
  if (runtime.mode === "OIDC" || runtime.mode === "DUAL") {
    const { auth } = await import("@/auth");
    const session = (await auth()) as
      | { ksiAccessToken?: string; ksiAuthError?: string }
      | null;
    if (session?.ksiAccessToken && !session.ksiAuthError) return session.ksiAccessToken;
    if (runtime.mode === "OIDC") throw new MissingSessionError();
  }

  const store = await cookies();
  const token = store.get(SESSION_COOKIE_NAME)?.value;
  if (!token) throw new MissingSessionError();
  return token;
}

// NODE_ENV==='production' 단독 조건은 이 제품이 HTTPS 없는 사내망 현장 서버로 배포될
// 경우(드론 파일럿 규모에서 드물지 않다) Secure 쿠키를 브라우저가 저장·전송하지 않아
// 로그인이 조용히 무한루프로 깨진다(독립 재검토 P2-B). 배포 환경이 HTTPS 종단이
// 아니라고 확인되면 이 env 로 명시적으로 끌 수 있게 한다 — 기본값은 안전한 쪽(HTTPS
// 전제)이고, 이 스위치를 켜는 것 자체가 배포 토폴로지 확인(공동 결정 레인) 신호다.
function cookieShouldBeSecure(): boolean {
  if (process.env.DASHBOARD_COOKIE_INSECURE_HTTP === "1") return false;
  return process.env.NODE_ENV === "production";
}

export async function setSessionToken(token: string): Promise<void> {
  const store = await cookies();
  store.set(SESSION_COOKIE_NAME, token, {
    httpOnly: true,
    secure: cookieShouldBeSecure(),
    sameSite: "lax",
    path: "/",
    // 무기한 쿠키 방지 — 재로그인 비용은 낮다(로그인 화면에 토큰 재입력만 하면 됨).
    maxAge: 60 * 60 * 8,
  });
}

export async function clearSessionToken(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE_NAME);
}
