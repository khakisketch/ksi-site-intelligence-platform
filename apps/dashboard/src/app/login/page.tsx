import { LoginForm } from "./LoginForm";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;

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
              발급받은 Bearer 토큰으로 로그인하세요.
            </p>
          </div>
          <LoginForm next={next ?? "/"} />
        </div>
      </div>
    </div>
  );
}
