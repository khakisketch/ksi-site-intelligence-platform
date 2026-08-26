export function loginNoticeText(input: {
  notice?: string;
  error?: string;
  localDevelopmentIdentityEnabled: boolean;
}): string | undefined {
  const { notice, error, localDevelopmentIdentityEnabled } = input;

  if (notice === "oidc-session-expired") {
    return localDevelopmentIdentityEnabled
      ? "개발 인증 서비스가 다시 시작되었거나 이전 세션이 만료되었습니다. 기본 개발 계정으로 다시 시작하세요."
      : "보안 세션을 갱신하지 못했습니다. 다시 로그인하세요.";
  }
  if (notice === "oidc-not-configured") return "OIDC 로그인이 이 환경에 설정되지 않았습니다.";

  // Auth.js intentionally exposes only a coarse error code in the redirect.
  // Never show that raw code as if it were an operator action.  Detailed causes
  // stay in server logs; the user gets the only safe recovery action.
  if (error) {
    return localDevelopmentIdentityEnabled
      ? "이전 로그인 요청을 검증하지 못했습니다. 이 화면에서 기본 개발 계정으로 다시 시작하세요."
      : "로그인 요청을 완료하지 못했습니다. 이 화면에서 다시 로그인하세요.";
  }
  return notice;
}
