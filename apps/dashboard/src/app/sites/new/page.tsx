import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { getSiteRegistrationAvailability } from "@/lib/core-api/permissions";

import { SiteRegistrationOnlyWizard } from "./SiteRegistrationOnlyWizard";

export default async function NewSitePage() {
  // 3상태로 읽는다 — 확정 거부만 막고, 확인 실패는 재시도 가능한 미확인으로
  // 보여준다(fail-closed: 어느 경우에도 마법사 진입은 열지 않는다).
  const availability = await getSiteRegistrationAvailability();

  if (availability.status === "unavailable") {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6 p-4 sm:p-5">
        <ErrorState
          message="등록 권한을 확인하지 못했습니다. 잠시 후 다시 확인하세요."
          retryable
        />
      </div>
    );
  }

  if (availability.status === "denied") {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6 p-4 sm:p-5">
        <EmptyState
          title="현장 등록 권한이 없습니다"
          description="현장 등록은 운영 권한을 가진 계정만 할 수 있습니다. 관리자에게 문의하세요."
        />
      </div>
    );
  }

  return (
    <ResponsiveActionBoundary
      action="SITE_DEVICE_TRANSITION"
      reason="현장 등록은 노트북의 전체 Operations Console에서 수행합니다."
      className="m-4 lg:m-5"
    >
      <SiteRegistrationOnlyWizard mode={availability.mode} />
    </ResponsiveActionBoundary>
  );
}
