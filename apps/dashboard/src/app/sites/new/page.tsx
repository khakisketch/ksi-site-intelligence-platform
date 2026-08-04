import { EmptyState } from "@/components/ui/EmptyState";
import { whoAmI } from "@/lib/core-api/auth";

import { SiteRegistrationOnlyWizard } from "./SiteRegistrationOnlyWizard";
import { SiteRegistrationWizard } from "./SiteRegistrationWizard";

// risk dashboard-wizard-rbac-mismatch — 현장 등록(SITES_WRITE)과 baseline 임무 발급
// (MISSIONS_ISSUE)을 동시에 요구하던 단일 흐름은 두 권한을 모두 가진 role(ADMIN)만
// 완주할 수 있었다. SITES_WRITE 만 있으면 등록까지만 진행하는 축약 Wizard로 보내고,
// 둘 다 있으면(주로 ADMIN) 기존 통합 흐름을 그대로 유지한다(회귀 없음).
export default async function NewSitePage() {
  let permissions: string[] = [];
  try {
    permissions = (await whoAmI()).permissions;
  } catch {
    // 세션 무효 — fail-closed, 아래 canRegisterSite=false 로 귀결(proxy.ts 가 정상 흐름에서는
    // 이미 /login 으로 보냈을 것이므로 여기 도달은 드문 경합/직접 URL 접근뿐이다).
  }
  const canRegisterSite = permissions.includes("SITES_WRITE");
  const canIssueMission = permissions.includes("MISSIONS_ISSUE");

  if (!canRegisterSite) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6 p-4 sm:p-5">
        <EmptyState
          title="현장 등록 권한이 없습니다"
          description="현장 등록은 현장 등록 권한을 가진 계정만 할 수 있습니다. 관리자에게 문의하세요."
        />
      </div>
    );
  }

  return canIssueMission ? <SiteRegistrationWizard /> : <SiteRegistrationOnlyWizard />;
}
