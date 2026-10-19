import Link from "next/link";

import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import type { SiteRegistrationAvailability } from "@/lib/core-api/permissions";

/**
 * 현장 목록 상단의 등록 진입. 허용이면 링크 그대로, 아니면 클릭해야 사유가
 * 열리는 ActionUnavailable — 상시 문구로 행 높이를 깨지 않는다(56.5px 문제).
 *
 * - denied: 확정 거부 — "현재 계정으로는 현장을 등록할 수 없습니다.
 *   관리자에게 문의하세요."
 * - unavailable: 확인 실패 — 재시도 버튼과 함께 "등록 권한을 확인하지
 *   못했습니다. 잠시 후 다시 확인하세요."
 */
export function RegisterSiteAction({
  availability,
}: {
  availability: SiteRegistrationAvailability;
}) {
  if (availability.status === "allowed") {
    return (
      <Link href="/sites/new" className="btn btn-primary tap-target">
        현장 등록
      </Link>
    );
  }
  if (availability.status === "unavailable") {
    return (
      <ActionUnavailable
        label="현장 등록"
        description="등록 권한을 확인하지 못했습니다. 잠시 후 다시 확인하세요."
        retry
      />
    );
  }
  return (
    <ActionUnavailable
      label="현장 등록"
      description="현재 계정으로는 현장을 등록할 수 없습니다. 관리자에게 문의하세요."
    />
  );
}
