export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    // 외부 VM profile의 OIDC·https origin·secret file 계약을 요청 전 기동 단계에서 검증한다.
    const { getDashboardAuthRuntime } = await import("@/lib/auth/runtime");
    getDashboardAuthRuntime();
  }
}
