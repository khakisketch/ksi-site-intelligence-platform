import { auth } from "@/auth";
import { AUTH_SESSION_COOKIE_NAME } from "@/lib/auth/auth-cookie";
import { getDashboardAuthRuntime } from "@/lib/auth/runtime";
import { NextResponse } from "next/server";

function expiredSessionResponse(request: Request & { cookies?: { getAll: () => Array<{ name: string }> } }) {
  const runtime = getDashboardAuthRuntime();
  const response = NextResponse.json({ code: "OIDC_SESSION_EXPIRED" }, { status: 401 });
  const sessionCookieNames = new Set<string>([AUTH_SESSION_COOKIE_NAME]);
  for (const cookie of request.cookies?.getAll() ?? []) {
    if (
      cookie.name === AUTH_SESSION_COOKIE_NAME ||
      cookie.name.startsWith(`${AUTH_SESSION_COOKIE_NAME}.`)
    ) {
      sessionCookieNames.add(cookie.name);
    }
  }
  for (const name of sessionCookieNames) {
    response.cookies.set({
      name,
      value: "",
      httpOnly: true,
      sameSite: "lax",
      secure: runtime.deploymentProfile === "EXTERNAL_VM",
      path: "/",
      maxAge: 0,
    });
  }
  return response;
}

export const POST = auth((request) => {
  const session = request.auth as
    | ({ ksiAccessToken?: string; ksiAuthError?: string } & NonNullable<typeof request.auth>)
    | null;
  if (!session?.ksiAccessToken || session.ksiAuthError) {
    // 무효 refresh token을 cookie에 남기면 이후 route마다 같은 401→login 루프가
    // 반복된다. base 및 Auth.js chunk cookie를 함께 만료시켜 다음 OIDC 시작은
    // 새 PKCE state로 이뤄지게 한다. 응답에는 token을 절대 포함하지 않는다.
    return expiredSessionResponse(request);
  }
  return new Response(null, { status: 204 });
});
