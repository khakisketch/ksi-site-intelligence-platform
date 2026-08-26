import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { parseDashboardAuthRuntime } from "@/lib/auth/runtime";
import {
  AUTH_CALLBACK_URL_COOKIE_NAME,
  AUTH_CSRF_COOKIE_NAME,
  AUTH_NONCE_COOKIE_NAME,
  AUTH_PKCE_COOKIE_NAME,
  AUTH_SESSION_COOKIE_NAME,
  AUTH_STATE_COOKIE_NAME,
  AUTH_TRANSIENT_COOKIE_MAX_AGE_SECONDS,
  AUTH_WEBAUTHN_CHALLENGE_COOKIE_NAME,
  authJsCookies,
} from "@/lib/auth/auth-cookie";
import { oidcAuthorizationParams, oidcLoginIntent } from "@/lib/auth/local-identity-login";
import { loginNoticeText } from "@/lib/auth/login-notice";

const secretReader = () => "s".repeat(32);

describe("Dashboard human auth deployment contract", () => {
  it("bare LOCAL은 Bearer 입력 대신 표준 local OIDC stack을 안내한다", () => {
    expect(parseDashboardAuthRuntime({}, secretReader)).toMatchObject({
      mode: "OPAQUE",
      deploymentProfile: "LOCAL",
      manualOpaqueLoginEnabled: false,
      localOidcStackRequired: true,
    });
  });

  it("LOCAL DUAL은 OIDC를 우선하고 legacy Bearer 입력을 기본으로 열지 않는다", () => {
    const config = parseDashboardAuthRuntime(
      {
        KSI_DASHBOARD_HUMAN_AUTH_MODE: "DUAL",
        KSI_DASHBOARD_OIDC_ISSUER: "http://local-issuer.test",
        KSI_DASHBOARD_OIDC_CLIENT_ID: "dashboard",
        KSI_DASHBOARD_SESSION_SECRET_FILE: "/secret/session",
        KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE: "/secret/client",
      },
      secretReader,
    );
    expect(config.manualOpaqueLoginEnabled).toBe(false);
    expect(config.localOidcStackRequired).toBe(false);
    expect(config.oidc?.clientId).toBe("dashboard");
  });

  it("명시적인 Local Identity stack만 기본 개발 계정 hint를 활성화한다", () => {
    const config = parseDashboardAuthRuntime(
      {
        KSI_DASHBOARD_HUMAN_AUTH_MODE: "OIDC",
        KSI_DASHBOARD_LOCAL_IDENTITY_ENABLED: "1",
        KSI_DASHBOARD_OIDC_ISSUER: "http://local-issuer.test",
        KSI_DASHBOARD_OIDC_CLIENT_ID: "dashboard",
        KSI_DASHBOARD_SESSION_SECRET_FILE: "/secret/session",
        KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE: "/secret/client",
      },
      secretReader,
    );
    expect(config.localDevelopmentIdentityEnabled).toBe(true);
    expect(oidcAuthorizationParams(config, "default")).toEqual({ login_hint: "local-admin" });
    expect(oidcAuthorizationParams(config, "role-test")).toEqual({ prompt: "select_account" });
    expect(oidcLoginIntent("role-test")).toBe("role-test");
    expect(oidcLoginIntent("untrusted-form-value")).toBe("default");
  });

  it("명시적 legacy 조사에서만 LOCAL opaque 입력을 연다", () => {
    const config = parseDashboardAuthRuntime(
      { KSI_DASHBOARD_LEGACY_OPAQUE_LOGIN_ENABLED: "1" },
      secretReader,
    );
    expect(config.manualOpaqueLoginEnabled).toBe(true);
    expect(config.localOidcStackRequired).toBe(false);
  });

  it("EXTERNAL_VM은 OIDC 외 mode를 기동 전에 거부한다", () => {
    expect(() =>
      parseDashboardAuthRuntime(
        { KSI_DASHBOARD_DEPLOYMENT_PROFILE: "EXTERNAL_VM" },
        secretReader,
      ),
    ).toThrow(/OIDC/);
  });

  it("EXTERNAL_VM은 https origins와 secret/OIDC 설정을 모두 요구한다", () => {
    const config = parseDashboardAuthRuntime(
      {
        KSI_DASHBOARD_DEPLOYMENT_PROFILE: "EXTERNAL_VM",
        KSI_DASHBOARD_HUMAN_AUTH_MODE: "OIDC",
        KSI_DASHBOARD_PUBLIC_APP_ORIGIN: "https://app.example.test",
        KSI_DASHBOARD_PUBLIC_API_ORIGIN: "https://api.example.test",
        KSI_DASHBOARD_OIDC_ISSUER: "https://id.example.test",
        KSI_DASHBOARD_OIDC_CLIENT_ID: "dashboard",
        KSI_DASHBOARD_SESSION_SECRET_FILE: "/secret/session",
        KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE: "/secret/client",
      },
      secretReader,
    );
    expect(config.manualOpaqueLoginEnabled).toBe(false);
    expect(config.localOidcStackRequired).toBe(false);
    expect(config.sessionSecret).toHaveLength(32);
  });

  it("EXTERNAL_VM http origin은 fail-closed다", () => {
    const base = {
      KSI_DASHBOARD_DEPLOYMENT_PROFILE: "EXTERNAL_VM",
      KSI_DASHBOARD_HUMAN_AUTH_MODE: "OIDC",
      KSI_DASHBOARD_PUBLIC_APP_ORIGIN: "http://app.example.test",
      KSI_DASHBOARD_PUBLIC_API_ORIGIN: "https://api.example.test",
      KSI_DASHBOARD_OIDC_ISSUER: "https://id.example.test",
      KSI_DASHBOARD_OIDC_CLIENT_ID: "dashboard",
      KSI_DASHBOARD_SESSION_SECRET_FILE: "/secret/session",
      KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE: "/secret/client",
    };
    expect(() => parseDashboardAuthRuntime(base, secretReader)).toThrow(/https origin/);
  });

  it("external profile은 Local Identity opt-in을 fail-closed로 거부한다", () => {
    expect(() =>
      parseDashboardAuthRuntime(
        {
          KSI_DASHBOARD_DEPLOYMENT_PROFILE: "EXTERNAL_VM",
          KSI_DASHBOARD_HUMAN_AUTH_MODE: "OIDC",
          KSI_DASHBOARD_LOCAL_IDENTITY_ENABLED: "1",
          KSI_DASHBOARD_PUBLIC_APP_ORIGIN: "https://app.example.test",
          KSI_DASHBOARD_PUBLIC_API_ORIGIN: "https://api.example.test",
          KSI_DASHBOARD_OIDC_ISSUER: "https://id.example.test",
          KSI_DASHBOARD_OIDC_CLIENT_ID: "dashboard",
          KSI_DASHBOARD_SESSION_SECRET_FILE: "/secret/session",
          KSI_DASHBOARD_OIDC_CLIENT_SECRET_FILE: "/secret/client",
        },
        secretReader,
      ),
    ).toThrow(/LOCAL OIDC/);
  });
});

describe("Auth.js token exposure boundary", () => {
  it("Authorization Code flow uses PKCE and encrypted JWT sessions", () => {
    const source = readFileSync(join(process.cwd(), "src/auth.ts"), "utf8");
    expect(source).toContain('checks: ["pkce", "state"]');
    expect(source).toContain('strategy: "jwt"');
    expect(source).toContain('error: "/login"');
    expect(source).toContain("authJsCookies");
    expect(source).toContain("refreshAccessToken");
    expect(source).toContain("coalescedRefresh");
  });

  it("isolates all Auth.js cookies from other applications on the same Tailnet host", () => {
    const cookies = authJsCookies(false);
    expect(cookies).toMatchObject({
      sessionToken: { name: AUTH_SESSION_COOKIE_NAME },
      callbackUrl: { name: AUTH_CALLBACK_URL_COOKIE_NAME },
      csrfToken: { name: AUTH_CSRF_COOKIE_NAME },
      pkceCodeVerifier: { name: AUTH_PKCE_COOKIE_NAME },
      state: { name: AUTH_STATE_COOKIE_NAME },
      nonce: { name: AUTH_NONCE_COOKIE_NAME },
      webauthnChallenge: { name: AUTH_WEBAUTHN_CHALLENGE_COOKIE_NAME },
    });
    expect(cookies.state.options).toMatchObject({
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      secure: false,
      maxAge: AUTH_TRANSIENT_COOKIE_MAX_AGE_SECONDS,
    });
    expect(cookies.pkceCodeVerifier.options.maxAge).toBe(AUTH_TRANSIENT_COOKIE_MAX_AGE_SECONDS);
    expect(cookies.webauthnChallenge.options.maxAge).toBe(AUTH_TRANSIENT_COOKIE_MAX_AGE_SECONDS);
    expect(cookies.state.name).not.toContain("authjs.");
  });

  it("sends an OAuth callback failure back to a usable login recovery state", () => {
    expect(
      loginNoticeText({ localDevelopmentIdentityEnabled: true, error: "Configuration" }),
    ).toMatch(/기본 개발 계정으로 다시 시작/);
    expect(
      loginNoticeText({ localDevelopmentIdentityEnabled: false, error: "Configuration" }),
    ).toBe("로그인 요청을 완료하지 못했습니다. 이 화면에서 다시 로그인하세요.");
  });

  it("browser refresh request is single-flight within a tab", () => {
    const source = readFileSync(
      join(process.cwd(), "src/components/auth/SessionRefresh.tsx"),
      "utf8",
    );
    expect(source).toContain("browserRefresh");
    expect(source).toContain("requestRefresh");
    expect(source).not.toContain("INITIAL_REFRESH_DELAY_MS");
    expect(source).not.toContain("window.setTimeout");
    expect(source).not.toContain("void refresh();\n    const interval");
  });

  it("browser session endpoint is closed while server refresh returns no token", () => {
    const sessionRoute = readFileSync(
      join(process.cwd(), "src/app/api/auth/[...nextauth]/route.ts"),
      "utf8",
    );
    const refreshRoute = readFileSync(
      join(process.cwd(), "src/app/api/auth/refresh/route.ts"),
      "utf8",
    );
    expect(sessionRoute).toContain('endsWith("/session")');
    expect(sessionRoute).toContain("status: 404");
    expect(refreshRoute).toContain("status: 204");
    expect(refreshRoute).not.toMatch(/accessToken\s*:/);
  });

  it("expired OIDC session clears base and chunked cookies before returning 401", () => {
    const refreshRoute = readFileSync(
      join(process.cwd(), "src/app/api/auth/refresh/route.ts"),
      "utf8",
    );
    expect(refreshRoute).toContain("AUTH_SESSION_COOKIE_NAME");
    expect(refreshRoute).toContain("startsWith(`${AUTH_SESSION_COOKIE_NAME}.`)");
    expect(refreshRoute).toContain("maxAge: 0");
  });
});
