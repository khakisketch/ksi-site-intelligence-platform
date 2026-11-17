import "server-only";

import { coreFetch, CoreApiError } from "./client";
import {
  isFeatureList,
  isJobPage,
  isProfileResultView,
  type MeasurementFeatureList,
  type SurfaceProfileJobPage,
  type SurfaceProfileResultView,
} from "./measurement-types";

export type {
  MeasurementFeatureList,
  MeasurementFeatureRevision,
  SurfaceProfileJobPage,
  SurfaceProfileJobView,
  SurfaceProfileResultView,
} from "./measurement-types";

function areaPath(siteId: string, workAreaId: string): string {
  return `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}`;
}

/** Core의 형식 계약을 어긴 응답은 숨긴다. 502로 올려 화면이 "불러오지 못함"을 정직하게 말한다. */
function malformed(): CoreApiError {
  return new CoreApiError(502, { verdict: "INVALID_CORE_RESPONSE" });
}

/** 작업구역에 저장된 측정 선의 최신 개정. 읽기만 하며 어떤 계산도 시작하지 않는다. */
export async function listMeasurementFeatures(siteId: string, workAreaId: string): Promise<MeasurementFeatureList> {
  const value = await coreFetch<unknown>(`${areaPath(siteId, workAreaId)}/measurement-features`);
  if (!isFeatureList(value)) throw malformed();
  return value;
}

/** 이 작업구역에서 요청한 단면 작업(최신순). 수치는 싣지 않고 상태와 영수증 사실만 담는다. */
export async function listSurfaceProfileJobs(
  siteId: string,
  workAreaId: string,
  options: { limit: number },
): Promise<SurfaceProfileJobPage> {
  const value = await coreFetch<unknown>(`${areaPath(siteId, workAreaId)}/surface-profile-jobs`, {
    query: { limit: options.limit },
  });
  if (!isJobPage(value)) throw malformed();
  return value;
}

/** 수치는 이 경로에서만 나온다. Core가 매번 현재 읽기 권한을 다시 확인한다. */
export async function getSurfaceProfileResult(
  siteId: string,
  workAreaId: string,
  jobId: string,
): Promise<SurfaceProfileResultView> {
  const value = await coreFetch<unknown>(
    `${areaPath(siteId, workAreaId)}/surface-profile-jobs/${encodeURIComponent(jobId)}/result`,
  );
  if (!isProfileResultView(value)) throw malformed();
  return value;
}
