import "server-only";

import { coreFetch, coreFetchWithToken, CoreApiError } from "./client";
import type { CreateLineBody, ReviseLineBody } from "@/lib/measurement-line";
import {
  isFeatureList,
  isFeatureRevision,
  isJobView,
  isJobPage,
  isProfileResultView,
  type MeasurementFeatureList,
  type MeasurementFeatureRevision,
  type SurfaceProfileJobView,
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

function unwrapRevision(value: unknown): MeasurementFeatureRevision {
  const revision = typeof value === "object" && value !== null ? (value as Record<string, unknown>).revision : null;
  if (!isFeatureRevision(revision)) throw malformed();
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
  return unwrapRevision(value);
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
  return unwrapRevision(value);
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
  body: { assetRef: string; feature: { featureId: string; revision: number; lineDigest: string }; heightDecisionId: string },
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
