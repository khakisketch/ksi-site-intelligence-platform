import Link from "next/link";

import { Disclosure } from "@/components/ui/Disclosure";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { PageHeader } from "@/components/ui/PageHeader";
import { logout } from "@/app/login/actions";
import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";
import { ROLE_LABEL } from "@/lib/core-api/labels";

// 셸이 "/more"의 h1("내 계정")을 소유한다 — 본문에는 맥락 제목 h2만 둔다.
//
// 넷째 탭은 계정과 도움말의 입구다. 현재 계정·로그아웃은 여기에,
// 작업 안내·지원 경계는 /help에 둔다. 계정 설정·결제·조직 관리처럼
// 구현되지 않은 기능을 채우기 위해 만들지 않는다.
export default async function MorePage() {
  let principal: Awaited<ReturnType<typeof whoAmI>> | null = null;
  let loginRequired = false;
  try {
    principal = await whoAmI();
  } catch (error) {
    if (error instanceof MissingSessionError || (error instanceof CoreApiError && error.status === 401)) {
      loginRequired = true;
    }
    // 그 밖의 실패(서버 연결 등)는 신원을 지어내지 않는다 — 아래에서 모름으로 둔다.
  }

  const roleLabel = principal ? (principal.role ? ROLE_LABEL[principal.role] : principal.kind) : null;

  return (
    <div className="console-page">
      <PageHeader title="내 계정" headingLevel={2} />
      <section aria-label="계정" className="flex w-full max-w-2xl flex-col gap-5 rounded-lg border border-line bg-surface p-5 sm:p-6">
        {principal ? (
          <div className="flex flex-wrap items-center gap-3">
            <span
              aria-hidden="true"
              className="grid size-12 flex-none place-items-center rounded-full bg-sunk text-title font-semibold"
            >
              {roleLabel?.charAt(0) || "?"}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-title font-semibold">{roleLabel}</p>
              <Disclosure label="계정 식별 상세">
                <p className="break-all text-caption text-ink-2">{principal.principalId}</p>
              </Disclosure>
            </div>
            <form action={logout} className="flex-none">
              <button type="submit" className="btn tap-target min-h-11">
                로그아웃
              </button>
            </form>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <InlineNotice>
              {loginRequired
                ? "로그인이 필요합니다. 로그인하면 현재 계정과 로그아웃을 여기서 확인할 수 있습니다."
                : "계정 정보를 확인할 수 없습니다. 서버 연결을 확인한 뒤 다시 시도하세요. 아래 로그아웃으로 세션을 정리할 수 있습니다."}
            </InlineNotice>
            <div className="flex flex-wrap gap-2">
              <Link href="/login" className="btn tap-target min-h-11">
                로그인
              </Link>
              <form action={logout}>
                <button type="submit" className="btn tap-target min-h-11">
                  로그아웃
                </button>
              </form>
            </div>
          </div>
        )}
      </section>

      <Link href="/help" className="tap-target flex w-full max-w-2xl items-center justify-between gap-4 border-t border-line py-4 text-body font-semibold hover:underline">도움말·작업 안내<svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="size-4"><path d="m7 4 6 6-6 6" /></svg></Link>
    </div>
  );
}
