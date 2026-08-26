"use server";

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { verifyToken } from "@/lib/core-api/auth";
import { oidcAuthorizationParams, oidcLoginIntent } from "@/lib/auth/local-identity-login";
import { getDashboardAuthRuntime } from "@/lib/auth/runtime";
import { safeNextPath } from "@/lib/auth/safe-next";
import {
  checkLoginThrottle,
  recordLoginFailure,
  recordLoginSuccess,
} from "@/lib/core-api/login-throttle";
import { clearSessionToken, setSessionToken } from "@/lib/core-api/session";

export interface LoginState {
  error?: string;
}

/**
 * 시도 제한 키 — 리버스 프록시 뒤에서는 x-forwarded-for 의 **첫** 값이 원 클라이언트다.
 *
 * 헤더가 전혀 없으면(비브라우저·직결) 하나의 공용 키로 묶는다. 개별 추적은 못 하지만
 * 그 상황에서도 무제한 추측은 막아야 한다 — 식별할 수 없다는 이유로 제한을 푸는 건
 * 공격자가 헤더를 지우기만 하면 되는 구조다.
 */
async function throttleKey(): Promise<string> {
  const store = await headers();
  const forwarded = store.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || store.get("x-real-ip") || "unidentified";
}

export async function login(_prevState: LoginState, formData: FormData): Promise<LoginState> {
  if (!getDashboardAuthRuntime().manualOpaqueLoginEnabled) {
    return { error: "이 배포에서는 수동 Bearer 토큰 로그인을 허용하지 않습니다." };
  }
  const key = await throttleKey();
  const throttle = checkLoginThrottle(key);
  if (throttle.blocked) {
    // 남은 시간을 말해준다 — "왜 안 되는지" 모르면 운영자는 계속 시도한다.
    return {
      error: `로그인 시도가 너무 많습니다. ${Math.ceil(throttle.retryAfterSeconds / 60)}분 후 다시 시도하세요.`,
    };
  }

  const token = String(formData.get("token") ?? "").trim();
  if (!token) {
    // 빈 입력은 추측 시도가 아니다 — 카운트하지 않는다(정상 사용자의 실수).
    return { error: "토큰을 입력하세요." };
  }

  let principal;
  try {
    principal = await verifyToken(token);
  } catch {
    // Core 서버 다운 등 네트워크 예외 — CoreApiError 가 아니라 verifyToken 이 그대로
    // 던진다(auth.ts). 처리 안 하면 Next 가 무자막 서버 오류로 흘려보낸다(독립 재검토 P2-D).
    return { error: "서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요." };
  }
  if (!principal) {
    recordLoginFailure(key);
    return { error: "유효하지 않은 토큰입니다. 다시 확인해 주세요." };
  }

  // 성공하면 카운터를 버린다 — 오타 몇 번 뒤 성공한 정상 운영자에게 잠금이 남으면
  // 안 된다(잠금이 정상 사용을 방해하면 운영자는 우회로를 찾는다).
  recordLoginSuccess(key);
  await setSessionToken(token);

  const nextParam = String(formData.get("next") ?? "/");
  redirect(safeNextPath(nextParam));
}

export async function oidcLogin(formData: FormData): Promise<void> {
  const runtime = getDashboardAuthRuntime();
  if (!runtime.oidc) redirect("/login?notice=oidc-not-configured");
  const { signIn } = await import("@/auth");
  await signIn("ksi-oidc", {
    redirectTo: safeNextPath(String(formData.get("next") ?? "/")),
  }, oidcAuthorizationParams(runtime, oidcLoginIntent(formData.get("intent"))));
}

export async function logout(): Promise<void> {
  await clearSessionToken();
  const runtime = getDashboardAuthRuntime();
  if (runtime.mode === "OIDC" || runtime.mode === "DUAL") {
    const { signOut } = await import("@/auth");
    await signOut({ redirectTo: "/login" });
  }
  redirect("/login");
}
