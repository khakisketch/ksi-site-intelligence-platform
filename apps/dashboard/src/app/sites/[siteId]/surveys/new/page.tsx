import { notFound } from "next/navigation";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getSpatialRefreshDraft } from "@/lib/core-api/region-extraction";
import { getSite } from "@/lib/core-api/sites";
import {
  resolveInitialMissionType,
  resolveReobservationCapturePreset,
} from "@/lib/core-api/surveyEntryPreset";
import type { AoiVertex, MissionDerivation, SiteView } from "@/lib/core-api/types";

import { SurveyWizard } from "./SurveyWizard";

type ReobservationCapturePreset = NonNullable<
  ReturnType<typeof resolveReobservationCapturePreset>
>;

/**
 * 변화 영역 화면(`/sites/[siteId]/changes`)의 "다음 비행 만들기"가 이 세 값을
 * 함께 넘긴다. AOI 자체는 URL 에 안 싣는다 — 매번 서버에서 다시 받아야 그
 * 사이 새 계산이 있었어도 항상 최신 초안을 쓴다("서버가 이미 아는 값을 다시
 * 묻지 않는다"와 반대로 읽힐 수 있지만, 여기서는 "클라이언트가 오래된 사본을
 * 들고 있지 않는다"가 우선한다 — 초안은 매번 새로 계산될 수 있는 값이다).
 *
 * 초안 조회는 한 번만 한다 — AOI 와 촬영 계획 제안이 같은 응답에서 나온다
 * (ADR-KSI-019 G5). 계보(`derivedFrom`)는 이 화면이 넘겨받은 세 식별자
 * 그대로다 — 서버가 발급 시점에 대조하지 않으므로 여기서도 재확인하지 않는다.
 */
async function resolveInitialSurvey(searchParams: {
  missionId?: string;
  changeRegionSetId?: string;
  regionId?: string;
}): Promise<{
  aoi: AoiVertex[] | null;
  capturePlan: ReobservationCapturePreset | null;
  derivation: MissionDerivation | null;
}> {
  const { missionId, changeRegionSetId, regionId } = searchParams;
  if (!missionId || !changeRegionSetId || !regionId) {
    return { aoi: null, capturePlan: null, derivation: null };
  }
  try {
    const draft = await getSpatialRefreshDraft(missionId, changeRegionSetId, regionId);
    const capturePlan = resolveReobservationCapturePreset(draft);
    return {
      aoi: draft.aoi ? draft.aoi.vertices : null,
      capturePlan,
      derivation: {
        sourceMissionId: missionId,
        changeRegionSetId,
        regionId,
        captureGrade: capturePlan?.grade ?? null,
      },
    };
  } catch {
    // 초안을 못 가져와도 마법사 진입 자체를 막지 않는다 — 빈 AOI로 시작해
    // 사람이 직접 그리면 된다(이 페이지의 다른 모든 조회 실패와 같은 원칙).
    return { aoi: null, capturePlan: null, derivation: null };
  }
}

// 새 현장조사 Wizard 진입점 — site 의 기존 siteFrame 을 재사용한다(새로 입력받지 않는다,
// UX 목표 §7 인증/데이터 정합 방침과 동일 정신: 서버가 이미 아는 값을 다시 묻지 않는다).
export default async function NewSurveyPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{
    purpose?: string;
    missionId?: string;
    changeRegionSetId?: string;
    regionId?: string;
  }>;
}) {
  const { siteId } = await params;
  const resolvedSearchParams = await searchParams;
  const { purpose } = resolvedSearchParams;
  const initialMissionType = resolveInitialMissionType(purpose);
  const { aoi: initialAoi, capturePlan: initialCapturePlan, derivation: initialDerivation } =
    await resolveInitialSurvey(resolvedSearchParams);

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

  return (
    <SurveyWizard
      site={site}
      initialMissionType={initialMissionType}
      initialAoi={initialAoi}
      initialCapturePlan={initialCapturePlan}
      initialDerivation={initialDerivation}
    />
  );
}
