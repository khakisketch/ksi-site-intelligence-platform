import Link from "next/link";

import { logout } from "@/app/login/actions";
import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";
import { ROLE_LABEL } from "@/lib/core-api/labels";
import { NAV_ITEMS } from "@/components/nav/nav-items";
import { NavIcon } from "@/components/nav/NavIcon";
import { StateBadge } from "@/components/ui/StatusBadge";

// TopBar 가 "/more" 경로 h1("계정·도움말") 을 이미 렌더한다(page-title.ts) — 여기서 또 찍지 않는다.
//
// 넷째 탭의 목적지는 계정·도움말이다. 범위 밖 장비 안내(Dock·Edge) 하나가
// 탭 전체를 차지하던 구조를 걷고, 현재 계정·로그아웃·작업 안내·지원 경계를
// 한 자리에서 연다. 계정 설정·결제·조직 관리 같은 화면은 이 제품에 없으므로
// 만들지 않는다.
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
  const showTeam = principal?.role === "ADMIN" || principal?.permissions?.includes("WORK_ORDERS_WRITE") === true;
  const boundaryItems = NAV_ITEMS.filter((item) => item.demoted);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 sm:p-5">
      <section aria-label="계정" className="flex flex-col gap-3 rounded-lg border border-line bg-surface px-4 py-3">
        <h2 className="text-[15px] font-bold">계정</h2>
        {principal ? (
          <div className="flex flex-wrap items-center gap-3">
            <span
              aria-hidden="true"
              className="grid size-9 flex-none place-items-center rounded-full bg-sunk text-[14px] font-bold"
            >
              {principal.principalId.trim().charAt(0).toUpperCase() || "?"}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block break-words text-[13.5px] font-semibold">{principal.principalId}</span>
              <span className="mt-0.5 block text-[12px] text-ink-2">{roleLabel}</span>
            </span>
            <form action={logout} className="flex-none">
              <button type="submit" className="btn tap-target min-h-11">
                로그아웃
              </button>
            </form>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <p className="text-[13px] leading-5 text-ink-2" role="status">
              {loginRequired
                ? "로그인이 필요합니다. 로그인하면 현재 계정과 로그아웃을 여기서 확인할 수 있습니다."
                : "계정 정보를 확인할 수 없습니다. 서버 연결을 확인한 뒤 다시 시도하세요. 아래 로그아웃으로 세션을 정리할 수 있습니다."}
            </p>
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

      <section aria-label="도움말·작업 안내" className="flex flex-col gap-2 rounded-lg border border-line bg-surface px-4 py-3">
        <h2 className="text-[15px] font-bold">도움말·작업 안내</h2>
        <p className="text-[12.5px] leading-5 text-ink-2">
          현장에서는 자료와 분석 결과를, 업무에서는 관측 작업과 배정·공유된 항목을 확인할 수 있습니다.
        </p>
        <ul className="flex flex-col divide-y divide-line">
          <li>
            <Link href="/sites" className="tap-target flex items-center gap-3 py-2.5 text-sm hover:underline">
              <span className="min-w-0 flex-1"><span className="block font-semibold">현장 목록</span>
                <span className="mt-0.5 block text-[12px] font-normal text-ink-muted">등록된 현장을 찾아 공간자료·등록 자료·분석 기록을 확인합니다.</span></span>
            </Link>
          </li>
          <li>
            <Link href="/field" className="tap-target flex items-center gap-3 py-2.5 text-sm hover:underline">
              <span className="min-w-0 flex-1"><span className="block font-semibold">관측 작업</span>
                <span className="mt-0.5 block text-[12px] font-normal text-ink-muted">조직의 관측 작업 기록을 상태별로 확인합니다. 개인 할당 목록이 아닙니다.</span></span>
            </Link>
          </li>
          <li>
            <Link href="/field/inbox" className="tap-target flex items-center gap-3 py-2.5 text-sm hover:underline">
              <span className="min-w-0 flex-1"><span className="block font-semibold">받은 업무</span>
                <span className="mt-0.5 block text-[12px] font-normal text-ink-muted">나에게 배정·공유된 작업과 결과를 확인합니다.</span></span>
            </Link>
          </li>
          {showTeam && <li>
            <Link href="/field/team" className="tap-target flex items-center gap-3 py-2.5 text-sm hover:underline">
              <span className="min-w-0 flex-1"><span className="block font-semibold">팀 관리</span>
                <span className="mt-0.5 block text-[12px] font-normal text-ink-muted">작업 배정·공유에 쓰는 팀원 정보를 확인합니다. 조직 관리 화면이 아닙니다.</span></span>
            </Link>
          </li>}
        </ul>
      </section>

      {boundaryItems.length > 0 && (
        <section aria-label="지원 경계 안내" className="flex flex-col gap-2 rounded-lg border border-line bg-surface px-4 py-3">
          <h2 className="text-[15px] font-bold">지원 경계 안내</h2>
          <p className="text-[12.5px] leading-5 text-ink-2">
            현재 제품의 지원 경계를 안내합니다. 장비 운용 기능은 제공하지 않습니다.
          </p>
          <ul className="flex flex-col divide-y divide-line">
            {boundaryItems.map((item) => (
              <li key={item.key}>
                <Link
                  href={item.href}
                  className="tap-target flex items-center gap-3 py-2.5 text-sm hover:bg-sunk"
                >
                  <NavIcon name={item.icon} className="size-5 flex-none text-ink-2" />
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold">{item.label}</span>
                    {item.description && (
                      <span className="mt-0.5 block text-[12px] font-normal text-ink-muted">{item.description}</span>
                    )}
                  </span>
                  {!item.implemented && <StateBadge label="제품 범위 밖" tone="neutral" />}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
