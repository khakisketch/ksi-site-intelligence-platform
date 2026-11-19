import "server-only";

import { coreFetch, coreFetchWithToken, CoreApiError } from "./client";
import type { CreateLineBody, ReviseLineBody } from "@/lib/measurement-line";
import {
  isFeatureList,
  isFeatureRevision,
  isJobView,
  isJobPage,
  isProfileResultView,
  isSurfaceProfileComparison,
  type MeasurementFeatureList,
  type MeasurementFeatureRef,
  type MeasurementFeatureRevision,
  type SurfaceProfileJobView,
  type SurfaceProfileJobPage,
  type SurfaceProfileResultView,
  type SurfaceProfileComparison,
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

export async function getMeasurementFeatureRevision(
  siteId: string, workAreaId: string, ref: MeasurementFeatureRef,
): Promise<MeasurementFeatureRevision> {
  const path = `${areaPath(siteId, workAreaId)}/measurement-features/${encodeURIComponent(ref.featureId)}/revisions/${ref.revision}`;
  const value = await coreFetch<unknown>(path);
  if (!isFeatureRevision(value) || value.siteId !== siteId || value.workAreaId !== workAreaId
    || value.featureId !== ref.featureId || value.revision !== ref.revision || value.lineDigest !== ref.lineDigest) throw malformed();
  return value;
}

/** 이 작업구역에서 요청한 단면 작업(최신순). 수치는 싣지 않고 상태와 영수증 사실만 담는다. */
export async function listSurfaceProfileJobs(
  siteId: string,
  workAreaId: string,
  options: { limit: number; featureId?: string; assetRef?: string; featureRevision?: number; executionGroup?: "ACTIVE" | "COMPLETED" },
): Promise<SurfaceProfileJobPage> {
  // 선을 지정하면 Core가 한도를 적용하기 전에 그 선의 작업만 남긴다. 다른 선의 작업이 이 선의 오래된 요청을 밀어내지 않는다.
  const query: Record<string, number | string | undefined> = {
    limit: options.limit,
    feature_id: options.featureId,
  };
  if (options.assetRef !== undefined) query.asset_ref = options.assetRef;
  if (options.featureRevision !== undefined) query.feature_revision = options.featureRevision;
  if (options.executionGroup !== undefined) query.execution_group = options.executionGroup;
  const value = await coreFetch<unknown>(`${areaPath(siteId, workAreaId)}/surface-profile-jobs`, {
    query,
  });
  if (!isJobPage(value)) throw malformed();
  if (value.items.some((item) =>
    item.siteId !== siteId || item.workAreaId !== workAreaId
    || (options.assetRef !== undefined && item.assetRef !== options.assetRef)
    || (options.featureId !== undefined && item.feature.featureId !== options.featureId)
    || (options.featureRevision !== undefined && item.feature.revision !== options.featureRevision)
    || (options.executionGroup === "ACTIVE" && item.executionState !== "QUEUED" && item.executionState !== "RUNNING")
    || (options.executionGroup === "COMPLETED" && item.executionState !== "COMPLETED")
  )) throw malformed();
  return value;
}

/** 저장된 비교를 다시 열 때 최근 목록 밖에 있는 작업도 고유 주소로 조회한다. */
export async function getSurfaceProfileJob(siteId: string, workAreaId: string, jobId: string): Promise<SurfaceProfileJobView> {
  const value = await coreFetch<unknown>(`${areaPath(siteId, workAreaId)}/surface-profile-jobs/${encodeURIComponent(jobId)}`);
  if (!isJobView(value) || value.jobId !== jobId || value.siteId !== siteId || value.workAreaId !== workAreaId) throw malformed();
  return value;
}

/** Core가 현재 읽기 권한을 확인한 수치와 영수증을 반환한다. */
export async function getSurfaceProfileResult(
  siteId: string,
  workAreaId: string,
  jobId: string,
  token?: string,
): Promise<SurfaceProfileResultView> {
  const path = `${areaPath(siteId, workAreaId)}/surface-profile-jobs/${encodeURIComponent(jobId)}/result`;
  const value = token === undefined ? await coreFetch<unknown>(path) : await coreFetchWithToken<unknown>(path, token);
  if (!isProfileResultView(value)) throw malformed();
  return value;
}

/** 저장된 두 단면의 차이를 Core가 독립 근거와 현재 권한으로 판정해 계산한다. */
export async function requestSurfaceProfileComparisonWithToken(
  siteId: string,
  workAreaId: string,
  body: { baselineJobId: string; currentJobId: string },
  idempotencyKey: string,
  token: string,
): Promise<SurfaceProfileComparison> {
  const value = await coreFetchWithToken<unknown>(
    `${areaPath(siteId, workAreaId)}/surface-profile-comparisons`,
    token,
    { method: "POST", body, headers: { "Idempotency-Key": idempotencyKey } },
  );
  if (!isSurfaceProfileComparison(value)) throw malformed();
  return value;
}

/** 이미 요청한 동일 비교를 최신 권한으로 다시 읽는다. 결과 파일을 내려받기 전에도 쓴다. */
export async function getSurfaceProfileComparisonWithToken(
  siteId: string,
  workAreaId: string,
  input: { baselineJobId: string; currentJobId: string; decisionId: string },
  token: string,
): Promise<SurfaceProfileComparison> {
  const value = await coreFetchWithToken<unknown>(
    `${areaPath(siteId, workAreaId)}/surface-profile-comparisons`,
    token,
    {
      query: {
        baseline_job_id: input.baselineJobId,
        current_job_id: input.currentJobId,
        decision_id: input.decisionId,
      },
    },
  );
  if (!isSurfaceProfileComparison(value) || value.baselineJobId !== input.baselineJobId
    || value.currentJobId !== input.currentJobId || value.decisionId !== input.decisionId) throw malformed();
  return value;
}

function unwrapRevision(value: unknown, siteId: string, workAreaId: string, expectedRevision: number, featureId?: string): MeasurementFeatureRevision {
  const revision = typeof value === "object" && value !== null ? (value as Record<string, unknown>).revision : null;
  if (!isFeatureRevision(revision) || revision.siteId !== siteId || revision.workAreaId !== workAreaId
    || revision.revision !== expectedRevision || (featureId !== undefined && revision.featureId !== featureId)) throw malformed();
  return revision;
}

/** 새 측정 선(개정 1). 같은 요청 토큰으로 계정 확인과 쓰기를 잇는다. 위치만 저장하며 어떤 자료도 읽지 않는다. */
export async function createMeasurementFeatureWithToken(
  siteId: string,
  workAreaId: string,
  body: CreateLineBody,
  idempotencyKey: string,
  token: string,
): Promise<MeasurementFeatureRevision> {
  const value = await coreFetchWithToken<unknown>(`${areaPath(siteId, workAreaId)}/measurement-features`, token, {
    method: "POST",
    body,
    headers: { "Idempotency-Key": idempotencyKey },
  });
  return unwrapRevision(value, siteId, workAreaId, 1);
}

/** 선을 고친다 = 새 개정. 이미 그 개정으로 읽은 단면은 그 개정에 묶인 채 남는다. */
export async function reviseMeasurementFeatureWithToken(
  siteId: string,
  workAreaId: string,
  featureId: string,
  body: ReviseLineBody,
  idempotencyKey: string,
  token: string,
): Promise<MeasurementFeatureRevision> {
  const value = await coreFetchWithToken<unknown>(
    `${areaPath(siteId, workAreaId)}/measurement-features/${encodeURIComponent(featureId)}/revisions`,
    token,
    { method: "POST", body, headers: { "Idempotency-Key": idempotencyKey } },
  );
  return unwrapRevision(value, siteId, workAreaId, body.expectedRevision + 1, featureId);
}

/** 한 DSM 자료의 높이 읽기 판정. BLOCKED도 사유와 함께 돌아오며, 화면은 이것으로 무엇이 모자란지 말한다. */
export interface AssetHeightDecision {
  decisionId: string;
  verdict: "ELIGIBLE" | "RESTRICTED" | "BLOCKED";
  reasons: string[];
  remediations: string[];
}

function isHeightDecision(value: unknown): value is AssetHeightDecision {
  if (typeof value !== "object" || value === null) return false;
  const decision = value as Record<string, unknown>;
  return typeof decision.decisionId === "string" && decision.decisionId.length > 0 && decision.decisionId.length <= 255
    && (decision.verdict === "ELIGIBLE" || decision.verdict === "RESTRICTED" || decision.verdict === "BLOCKED")
    && Array.isArray(decision.reasons) && decision.reasons.every((item) => typeof item === "string")
    && Array.isArray(decision.remediations) && decision.remediations.every((item) => typeof item === "string");
}

/** 자료 참조로 높이 판정을 요청한다. 범위가 제한된 운영자도 닿는 경로이며, 판정 규칙은 Core가 그대로 적용한다. */
export async function requestAssetHeightDecisionWithToken(
  siteId: string,
  workAreaId: string,
  assetRef: string,
  idempotencyKey: string,
  token: string,
): Promise<AssetHeightDecision> {
  const value = await coreFetchWithToken<unknown>(
    `${areaPath(siteId, workAreaId)}/spatial-assets/${encodeURIComponent(assetRef)}/height-decision`,
    token,
    { method: "POST", headers: { "Idempotency-Key": idempotencyKey } },
  );
  const decision = typeof value === "object" && value !== null ? (value as Record<string, unknown>).decision : null;
  if (!isHeightDecision(decision)) throw malformed();
  return decision;
}

/** 단면 작업을 발급한다. 선은 본문에 싣지 않고 저장된 개정을 가리킨다. */
export async function issueSurfaceProfileJobWithToken(
  siteId: string,
  workAreaId: string,
  body: { assetRef: string; feature: { featureId: string; revision: number; lineDigest: string }; heightDecisionId: string; sampleSpacingM?: number },
  idempotencyKey: string,
  token: string,
): Promise<SurfaceProfileJobView> {
  const value = await coreFetchWithToken<unknown>(`${areaPath(siteId, workAreaId)}/surface-profile-jobs`, token, {
    method: "POST",
    body,
    headers: { "Idempotency-Key": idempotencyKey },
  });
  if (!isJobView(value)) throw malformed();
  return value;
}

export async function cancelSurfaceProfileJobWithToken(
  siteId: string,
  workAreaId: string,
  jobId: string,
  token: string,
): Promise<SurfaceProfileJobView> {
  const value = await coreFetchWithToken<unknown>(
    `${areaPath(siteId, workAreaId)}/surface-profile-jobs/${encodeURIComponent(jobId)}/cancel`,
    token,
    { method: "POST" },
  );
  if (!isJobView(value)) throw malformed();
  return value;
}
