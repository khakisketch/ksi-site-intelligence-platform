import { LoginForm } from "./LoginForm";
import { loginNoticeText } from "@/lib/auth/login-notice";
import { getDashboardAuthRuntime } from "@/lib/auth/runtime";

import { oidcLogin } from "./actions";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; notice?: string; error?: string }>;
}) {
  const { next, notice, error } = await searchParams;
  const runtime = getDashboardAuthRuntime();
  const noticeText = loginNoticeText({
    notice,
    error,
    localDevelopmentIdentityEnabled: runtime.localDevelopmentIdentityEnabled,
  });
  const localIdentity = runtime.localDevelopmentIdentityEnabled;

  return (
    <div className="flex min-h-full flex-1 items-center justify-center p-4 sm:p-6">
      <div className="w-full max-w-sm">
        {/* 브랜드 마크를 카드 위에 둬 "앱 진입"으로 읽히게 한다 — DesktopSidebar의
            같은 마크(bg-accent · text-accent-on · rounded-md)와 일치시킨다. */}
        <div className="mb-5 flex justify-center">
          <span
            aria-hidden="true"
            className="grid size-9 place-items-center rounded-md bg-accent text-[13px] font-extrabold tracking-tight text-accent-on"
          >
            KSI
          </span>
        </div>
        <div className="rounded-lg border border-line bg-surface p-6">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="text-lg font-medium break-keep">KSI Site Intelligence</h1>
            <p className="break-keep text-sm text-ink-muted">
              {localIdentity
                ? "기본 개발 계정으로 KSI Operations Console을 시작하세요."
                : "조직 계정으로 KSI Operations Console에 로그인하세요."}
            </p>
          </div>
          {noticeText && (
            <p
              role="status"
              className={`mb-4 rounded-md px-3 py-2 text-sm ${
                localIdentity ? "bg-low-bg text-low-ink" : "bg-high-bg text-high-ink"
              }`}
            >
              {noticeText}
            </p>
          )}
          {runtime.oidc && (
            <form action={oidcLogin}>
              <input type="hidden" name="next" value={next ?? "/"} />
              {localIdentity && <input type="hidden" name="intent" value="default" />}
              <button type="submit" className="btn btn-primary w-full">
                {localIdentity ? "개발 Operations Console 시작" : "조직 계정으로 로그인"}
              </button>
            </form>
          )}
          {runtime.oidc && localIdentity && (
            <details className="mt-5 border-t border-line pt-4 text-sm">
              <summary className="cursor-pointer font-medium text-ink-muted">
                권한별 화면 테스트
              </summary>
              <p className="mt-2 break-keep text-sm text-ink-muted">
                RBAC와 읽기 전용 화면을 확인할 때만 다른 합성 개발 계정을 선택하세요.
              </p>
              <form action={oidcLogin} className="mt-3">
                <input type="hidden" name="next" value={next ?? "/"} />
                <input type="hidden" name="intent" value="role-test" />
                <button type="submit" className="btn w-full">
                  다른 개발 계정 선택
                </button>
              </form>
            </details>
          )}
          {runtime.oidc && runtime.manualOpaqueLoginEnabled && (
            <div className="my-5 flex items-center gap-3 text-xs text-ink-muted" aria-hidden="true">
              <span className="h-px flex-1 bg-line" />개발 migration<span className="h-px flex-1 bg-line" />
            </div>
          )}
          {runtime.manualOpaqueLoginEnabled && <LoginForm next={next ?? "/"} />}
          {runtime.localOidcStackRequired && (
            <p role="status" className="rounded-md bg-low-bg px-3 py-2 text-sm text-low-ink">
              로컬 개발은 OIDC 로그인 흐름으로 실행합니다. Dashboard 폴더에서 <code>npm run dev</code>
              를 실행하세요.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
