import NextAuth, { type NextAuthConfig } from "next-auth";

import {
  AUTH_SESSION_MAX_AGE_SECONDS,
  authJsCookies,
} from "@/lib/auth/auth-cookie";
import { coalescedRefresh } from "@/lib/auth/coalesced-refresh";
import { getDashboardAuthRuntime } from "@/lib/auth/runtime";

const runtime = getDashboardAuthRuntime();

interface KsiJwt {
  accessToken?: string;
  accessTokenExpiresAt?: number;
  refreshToken?: string;
  authError?: "RefreshTokenError";
}

let discoveryPromise: Promise<{ token_endpoint?: string }> | undefined;

async function tokenEndpoint(): Promise<string> {
  if (!runtime.oidc) throw new Error("OIDC runtime이 설정되지 않았습니다.");
  discoveryPromise ??= fetch(
    `${runtime.oidc.issuer.replace(/\/$/, "")}/.well-known/openid-configuration`,
    { headers: { Accept: "application/json" }, cache: "no-store" },
  ).then(async (response) => {
    if (!response.ok) throw new Error(`OIDC discovery 실패: ${response.status}`);
    return (await response.json()) as { token_endpoint?: string };
  });
  const discovery = await discoveryPromise;
  if (!discovery.token_endpoint) throw new Error("OIDC discovery에 token_endpoint가 없습니다.");
  return discovery.token_endpoint;
}

async function performRefreshAccessToken(token: KsiJwt): Promise<KsiJwt> {
  if (!runtime.oidc || !token.refreshToken) return { ...token, authError: "RefreshTokenError" };
  try {
    const response = await fetch(await tokenEndpoint(), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: token.refreshToken,
        client_id: runtime.oidc.clientId,
        client_secret: runtime.oidc.clientSecret,
      }),
      cache: "no-store",
    });
    const refreshed = (await response.json()) as {
      access_token?: string;
      expires_in?: number;
      refresh_token?: string;
    };
    if (!response.ok || !refreshed.access_token) throw new Error("OIDC refresh가 거부되었습니다.");
    return {
      accessToken: refreshed.access_token,
      accessTokenExpiresAt: Date.now() + (refreshed.expires_in ?? 300) * 1000,
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
    };
  } catch {
    return { ...token, accessToken: undefined, authError: "RefreshTokenError" };
  }
}

function refreshAccessToken(token: KsiJwt): Promise<KsiJwt> {
  if (!token.refreshToken) return Promise.resolve({ ...token, authError: "RefreshTokenError" });
  // Auth.js JWT cookie 갱신과 동시에 시작된 Server Component/Route Handler 요청은
  // 첫 응답이 cookie를 쓰기 전에 같은 이전 refresh token을 들고 도착할 수 있다.
  // 회전 결과를 짧게 재사용해 provider의 1회용 token을 다시 소비하지 않는다.
  return coalescedRefresh(token.refreshToken, () => performRefreshAccessToken(token), {
    reuseForMs: 5_000,
  });
}

const providers: NextAuthConfig["providers"] = runtime.oidc
  ? [
      {
        id: "ksi-oidc",
        name: "KSI Identity",
        type: "oidc",
        issuer: runtime.oidc.issuer,
        clientId: runtime.oidc.clientId,
        clientSecret: runtime.oidc.clientSecret,
        checks: ["pkce", "state"],
        authorization: { params: { scope: "openid profile offline_access" } },
      },
    ]
  : [];

export const authConfig: NextAuthConfig = {
  providers,
  secret: runtime.sessionSecret,
  // loopback local issuer도 callback host를 신뢰해야 실제 Authorization Code+PKCE
  // 왕복을 검증할 수 있다. EXTERNAL_VM은 TLS ingress가 유일한 public host다.
  trustHost: runtime.deploymentProfile === "EXTERNAL_VM" || runtime.mode === "OIDC",
  // Invalid/expired OAuth state is a recovery flow, not a generic framework
  // error page.  `/login` is public, and gives the operator a fresh start.
  pages: { signIn: "/login", error: "/login" },
  session: { strategy: "jwt", maxAge: AUTH_SESSION_MAX_AGE_SECONDS },
  cookies: authJsCookies(runtime.deploymentProfile === "EXTERNAL_VM"),
  callbacks: {
    async jwt({ token, account }) {
      const ksi = token as typeof token & KsiJwt;
      if (account) {
        ksi.accessToken = account.access_token;
        ksi.accessTokenExpiresAt = (account.expires_at ?? Math.floor(Date.now() / 1000) + 300) * 1000;
        ksi.refreshToken = account.refresh_token;
        ksi.authError = undefined;
        return ksi;
      }
      if (ksi.accessToken && Date.now() < (ksi.accessTokenExpiresAt ?? 0) - 60_000) return ksi;
      return { ...ksi, ...(await refreshAccessToken(ksi)) };
    },
    session({ session, token }) {
      // 이 두 필드는 서버 auth() 호출에서만 소비한다. /api/auth/session은 route에서
      // 404로 닫아 access/refresh token이 브라우저 JavaScript에 노출되지 않게 한다.
      const serverSession = session as typeof session & {
        ksiAccessToken?: string;
        ksiAuthError?: string;
      };
      serverSession.ksiAccessToken = (token as KsiJwt).accessToken;
      serverSession.ksiAuthError = (token as KsiJwt).authError;
      return serverSession;
    },
  },
};

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
