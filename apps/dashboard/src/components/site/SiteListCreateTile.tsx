import Link from "next/link";

import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import type { SiteRegistrationAvailability } from "@/lib/core-api/permissions";

/**
 * 갤러리 마지막 줄의 `+ 새 현장 추가` 타일 — 실제 현장 카드와 같은 틀,
 * 점선으로만 구분한다. 목록 개수·정렬·페이지 계산에는 절대 들어가지 않는다
 * (호출부가 마지막 페이지에만 꽂는다).
 */

const TILE_FRAME =
  "flex min-h-[160px] w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line-strong bg-surface p-4 text-center text-[13px] font-semibold text-ink-1 transition-colors hover:border-ink-muted";

function PlusMark() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      className="size-6"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
    >
      <path d="M8 3v10M3 8h10" strokeLinecap="round" />
    </svg>
  );
}

function TileFace() {
  return (
    <>
      <PlusMark />
      <span>새 현장 추가</span>
    </>
  );
}
const DENIED_DESCRIPTION = "현재 계정으로는 현장을 등록할 수 없습니다. 관리자에게 문의하세요.";
const UNAVAILABLE_DESCRIPTION = "등록 권한을 확인할 수 없었습니다. 잠시 후 다시 확인하세요.";

/**
 * 등록 게이트 3상태를 타일 하나로 보여준다. 판정은 호출부가 준
 * `getSiteRegistrationAvailability()` 그대로 쓰고, 여기서 권한을 추론하지
 * 않는다. 막힌 상태는 이동·쓰기 없이 사유 팝오버만 연다.
 */
export function SiteListCreateTile({
  availability,
}: {
  availability: SiteRegistrationAvailability;
}) {
  if (availability.status === "allowed") {
    return (
      <Link href="/sites/new" data-site-create-card="new" className={TILE_FRAME}>
        <TileFace />
      </Link>
    );
  }
  return (
    <ActionUnavailable
      label="새 현장 추가"
      description={availability.status === "unavailable" ? UNAVAILABLE_DESCRIPTION : DENIED_DESCRIPTION}
      retry={availability.status === "unavailable"}
      trigger={
        <span data-site-create-card="new" className="contents">
          <TileFace />
        </span>
      }
      triggerClassName={`${TILE_FRAME} w-full flex-1 cursor-pointer`}
    />
  );
}
