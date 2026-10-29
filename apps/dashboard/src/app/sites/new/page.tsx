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
      reason="등록은 노트북 이상의 화면에서 같은 계정으로 현장 목록을 열어 시작하세요. 입력 중인 지도 경계가 있다면 이 탭의 화면 폭을 1024px 이상으로 넓혀 완료하거나 취소하세요. 이 탭의 입력은 다른 기기로 옮겨지지 않습니다."
      className="m-4 lg:m-5"
    >
      <SiteRegistrationOnlyWizard
        mode={availability.mode}
        accountFingerprint={availability.accountFingerprint ?? null}
      />
    </ResponsiveActionBoundary>
  );
}
