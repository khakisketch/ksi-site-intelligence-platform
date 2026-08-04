import { notFound } from "next/navigation";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getSite } from "@/lib/core-api/sites";
import type { SiteView } from "@/lib/core-api/types";

import { SurveyWizard } from "./SurveyWizard";

// 새 현장조사 Wizard 진입점 — site 의 기존 siteFrame 을 재사용한다(새로 입력받지 않는다,
// UX 목표 §7 인증/데이터 정합 방침과 동일 정신: 서버가 이미 아는 값을 다시 묻지 않는다).
export default async function NewSurveyPage({
  params,
}: {
  params: Promise<{ siteId: string }>;
}) {
  const { siteId } = await params;

  // 데이터 조회는 JSX 생성과 분리한다 — sites/[siteId]/page.tsx 와 동일 관례
  // (try/catch 안에서 JSX 를 만들면 렌더 시점에 못 잡는 에러가 된다).
  let site: SiteView | null = null;
  let errorMessage: string | null = null;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      notFound();
    }
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  if (errorMessage !== null || site === null) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6 p-4 sm:p-5">
        <ErrorState message={errorMessage ?? "요청을 처리하지 못했습니다."} />
      </div>
    );
  }

  // risk dashboard-wizard-rbac-mismatch — 임무 발급 권한 없이 진입하면 마지막 제출
  // 단계에서만 실패가 드러난다(입력을 다 채운 뒤 403). 진입 시점에 미리 막는다.
  const canIssueMission = await hasAllPermissions("MISSIONS_ISSUE");
  if (!canIssueMission) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6 p-4 sm:p-5">
        <EmptyState
          title="조사 임무 발급 권한이 없습니다"
          description="새 현장조사는 임무 발급 권한을 가진 계정만 시작할 수 있습니다. 관리자에게 문의하세요."
        />
      </div>
    );
  }

  return <SurveyWizard site={site} />;
}
