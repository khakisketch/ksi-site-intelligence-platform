import Link from "next/link";

import { logout } from "@/app/login/actions";
import { whoAmI } from "@/lib/core-api/auth";
import type { WhoAmIResponse } from "@/lib/core-api/types";
import { ROLE_LABEL } from "@/lib/core-api/labels";

/** 레일 하단 사용자 블록 — 이니셜 · 이름 · 역할 · 로그아웃(디자인 §0).
 *
 * 사용자 신원이 상단바에서 레일 하단으로 내려온 것은 디자인의 판단이다: 상단바는
 * **지금 보고 있는 화면**에 관한 줄이고(제목·수신 상태·시각), 신원은 화면이 바뀌어도
 * 그대로인 값이라 셸의 고정된 구석에 두는 편이 읽는 부담이 적다.
 *
 * 역할 전환(FIELD_OPERATOR/ADMIN/VIEWER)은 프로토타입의 시연 장치라 옮기지 않았다 —
 * 실제 역할은 httpOnly 쿠키의 bearer token 이 정하고 화면이 바꿀 수 있는 값이 아니다.
 * 여기서는 **현재 역할을 밝히는 것**까지만 한다(README "역할 · 세션" 항).
 */
export async function SidebarUserBlock({ snapshot }: { snapshot?: WhoAmIResponse | null } = {}) {
  let principal = snapshot;
  try {
    if (principal === undefined) principal = await whoAmI();
  } catch {
    // 세션이 없거나 만료된 경우 — 여기서 재로그인 유도를 또 하지 않는다. 상단바가
    // 이미 그 자리를 갖고 있고(TopBar), 레일 하단까지 같은 문구를 겹치면 화면이
    // 고장난 것처럼 보인다. 조용히 비운다.
    return null;
  }

  if (!principal) return null;
  const roleLabel = principal.role ? ROLE_LABEL[principal.role] : principal.kind;
  const initial = principal.principalId.trim().charAt(0).toUpperCase() || "?";

  return (
    <div className="mt-auto flex items-center gap-[9px] border-t border-white/[0.08] px-3 pt-2.5">
      <span
        aria-hidden="true"
        className="grid size-[27px] flex-none place-items-center rounded-full bg-sidebar-active text-[11.5px] font-bold text-sidebar-active-ink"
      >
        {initial}
      </span>
      <span className="min-w-0 flex-1">
        <Link
          href="/more"
          className="tap-target block truncate text-[12.5px] font-semibold hover:underline"
        >
          {principal.principalId}
        </Link>
        <span className="block truncate text-[11px] text-sidebar-muted">{roleLabel}</span>
      </span>
      <form action={logout} className="flex-none">
        <button
          type="submit"
          className="tap-target flex items-center rounded-md px-2 text-[11.5px] text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-text"
        >
          로그아웃
        </button>
      </form>
    </div>
  );
}
