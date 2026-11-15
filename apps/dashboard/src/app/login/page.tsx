import { LoginForm } from "./LoginForm";
import { OidcLoginButton } from "./OidcLoginButton";
import { loginNoticeText } from "@/lib/auth/login-notice";
import { getDashboardAuthRuntime } from "@/lib/auth/runtime";

import { oidcLogin } from "./actions";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; notice?: string; error?: string; intent?: string }>;
}) {
  const { next, notice, error, intent } = await searchParams;
  const runtime = getDashboardAuthRuntime();
  const noticeText = loginNoticeText({
    notice,
    error,
    localDevelopmentIdentityEnabled: runtime.localDevelopmentIdentityEnabled,
  });
  const localIdentity = runtime.localDevelopmentIdentityEnabled;
  // 권한별 화면 점검용 계정 선택은 평소 화면에 두지 않고 주소로만 연다.
  const showRoleTest = localIdentity && intent === "role-test";

  return (
    <div className="flex min-h-full flex-1 items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-sm">
        {/* 브랜드 마크를 카드 위에 둬 "앱 진입"으로 읽히게 한다 — DesktopSidebar의
            같은 마크(bg-accent · text-accent-on · rounded-md)와 일치시킨다. */}
        <div className="mb-5 flex justify-center">
          <span
            aria-hidden="true"
            className="grid size-9 place-items-center rounded-md bg-accent text-body font-extrabold tracking-tight text-accent-on"
          >
            KSI
          </span>
        </div>
        <div className="rounded-lg border border-line bg-surface p-6">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-title font-medium break-keep">KSI Site Intelligence</h1>
            <p className="text-body leading-6 break-keep text-ink-2">공간 자료와 분석 결과를 확인하고, 검토 기록을 남깁니다.</p>
            {localIdentity && (
              <p className="break-keep text-caption text-ink-muted">개발 환경입니다. 기본 개발 계정으로 시작합니다.</p>
            )}
          </div>
          {noticeText && (
            <p
              role="status"
              className={`mb-4 rounded-md px-3 py-2 text-body ${
                localIdentity ? "bg-sunk text-ink-1" : "bg-high-bg text-high-ink"
              }`}
            >
              {noticeText}
            </p>
          )}
          {runtime.oidc && (
            <form action={oidcLogin}>
              <input type="hidden" name="next" value={next ?? "/"} />
              {localIdentity && <input type="hidden" name="intent" value="default" />}
              <OidcLoginButton
                label={localIdentity ? "개발 Operations Console 시작" : "조직 계정으로 로그인"}
                className="btn btn-primary tap-target w-full"
              />
            </form>
          )}
          {runtime.oidc && showRoleTest && (
            <form action={oidcLogin} className="mt-4">
              <input type="hidden" name="next" value={next ?? "/"} />
              <input type="hidden" name="intent" value="role-test" />
              <OidcLoginButton label="다른 개발 계정 선택" className="btn btn-quiet w-full" />
            </form>
          )}
          {runtime.oidc && runtime.manualOpaqueLoginEnabled && (
            <div className="my-5 flex items-center gap-3 text-caption text-ink-muted" aria-hidden="true">
              <span className="h-px flex-1 bg-line" />개발 migration<span className="h-px flex-1 bg-line" />
            </div>
          )}
          {runtime.manualOpaqueLoginEnabled && <LoginForm next={next ?? "/"} />}
          {runtime.localOidcStackRequired && (
            <p role="status" className="rounded-md bg-sunk px-3 py-2 text-body text-ink-1">
              로컬 개발은 OIDC 로그인 흐름으로 실행합니다. Dashboard 폴더에서 <code>npm run dev</code>
              를 실행하세요.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
