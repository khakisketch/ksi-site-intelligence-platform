import { EmptyState } from "@/components/ui/EmptyState";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { hasAllPermissions } from "@/lib/core-api/permissions";

import { SiteRegistrationOnlyWizard } from "./SiteRegistrationOnlyWizard";

// ADR-KSI-015 이후 SITES_WRITE 를 가진 역할(ADMIN·FIELD_OPERATOR)은 항상
// MISSIONS_ISSUE 도 함께 갖는다 — 그래도 둘을 각각(AND) 요구한다(fail-closed).
// 표가 다시 갈라져도(예: 신규 역할 추가) 발급 권한 없이 임무 발급까지 요구하는
// 통합 흐름에 들어가는 반쪽 상태를 만들지 않기 위해서다.
//
// 예전엔 이 두 권한 보유 여부로 SiteRegistrationWizard(통합)/
// SiteRegistrationOnlyWizard(등록만) 를 **자동으로** 갈랐다 — 3역할 체계에서는
// 두 권한이 항상 같이 붙어 있어 그 분기가 도달 불가가 됐다(SITES_WRITE 를 가진
// 역할은 항상 MISSIONS_ISSUE 도 갖는다). "등록만 하고 임무는 나중"은 RBAC 의
// 산물이 아니라 도메인의 산물이다(UNMAPPED 가 정상 중간 상태) — 그래서 이제는
// 권한이 아니라 **사용자 선택**으로 두 흐름을 가른다.
export default async function NewSitePage() {
  const canRegisterWithMission = await hasAllPermissions("SITES_WRITE", "MISSIONS_ISSUE");

  if (!canRegisterWithMission) {
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
      <SiteRegistrationOnlyWizard />
    </ResponsiveActionBoundary>
  );
}
