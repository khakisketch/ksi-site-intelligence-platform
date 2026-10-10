import { EmptyState } from "@/components/ui/EmptyState";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { getSiteRegistrationMode } from "@/lib/core-api/permissions";

import { SiteRegistrationOnlyWizard } from "./SiteRegistrationOnlyWizard";

export default async function NewSitePage() {
  const mode = await getSiteRegistrationMode();

  if (mode === "DENIED") {
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
      <SiteRegistrationOnlyWizard mode={mode} />
    </ResponsiveActionBoundary>
  );
}
