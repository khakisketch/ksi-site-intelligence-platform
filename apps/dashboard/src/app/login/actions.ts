"use server";

import { redirect } from "next/navigation";

import { verifyToken } from "@/lib/core-api/auth";
import { clearSessionToken, setSessionToken } from "@/lib/core-api/session";

export interface LoginState {
  error?: string;
}

// 오픈 리다이렉트 방지 — 문자열 startsWith("/") 검사는 "/\evil.com"·탭 삽입 등
// WHATWG URL 파서가 별도로 정규화하는 트릭에 우회당한다(독립 재검토 1차 P1-B). 브라우저와
// 동일한 파서로 정규화한 뒤 origin 을 대조해야 안전하다.
function safeNextPath(raw: string): string {
  try {
    const parsed = new URL(raw, "http://ksi-dashboard.invalid");
    if (parsed.origin !== "http://ksi-dashboard.invalid") return "/";
    const path = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    // origin 대조만으로는 부족하다 — "/.//evil.example"·"/..//evil.example" 류는 dot-segment
    // 정규화로 parsed.pathname 자체가 "//evil.example"(scheme-relative)이 되어 origin 은
    // base 그대로 통과한다(독립 재검토 2차 P1-B). "/"로 시작하되 "//"는 아닌 형태만 허용해
    // pathname의 shape 자체를 명시적으로 검사한다(암묵적 불변식에 기대지 않는다).
    if (!path.startsWith("/") || path.startsWith("//")) return "/";
    return path;
  } catch {
    return "/";
  }
}

export async function login(_prevState: LoginState, formData: FormData): Promise<LoginState> {
  const token = String(formData.get("token") ?? "").trim();
  if (!token) {
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
    return { error: "유효하지 않은 토큰입니다. 다시 확인해 주세요." };
  }

  await setSessionToken(token);

  const nextParam = String(formData.get("next") ?? "/");
  redirect(safeNextPath(nextParam));
}

export async function logout(): Promise<void> {
  await clearSessionToken();
  redirect("/login");
}
