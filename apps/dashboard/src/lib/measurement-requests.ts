import type { MeasurementFeatureRef, SurfaceProfileJobView } from "@/lib/core-api/measurement-types";

/**
 * 날짜(자료)별 단면 요청 상태. 선택한 선의 정확한 개정(선 모양 digest까지 같은 것)에 대한 작업만 센다.
 * 다른 개정으로 읽은 결과는 이 선의 결과가 아니므로 "요청 없음"으로 둔다.
 */

export type RequestState = "none" | "active" | "done" | "unavailable" | "failed" | "canceled";

export interface RequestRow {
  assetRef: string;
  label: string;
  state: RequestState;
  /** 취소·결과 확인에 쓰는 가장 최근 작업. 요청이 없으면 null이다. */
  jobId: string | null;
  /** 실패 사유 코드(failed) 또는 지금 읽을 수 없는 이유의 가용성 값(unavailable). */
  reason: string | null;
}

const newestFirst = (a: SurfaceProfileJobView, b: SurfaceProfileJobView) =>
  a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : a.jobId < b.jobId ? 1 : -1;

export function requestRows(input: {
  assets: readonly { assetRef: string; label: string }[];
  jobs: readonly SurfaceProfileJobView[];
  feature: MeasurementFeatureRef;
}): RequestRow[] {
  const exact = input.jobs
    .filter((job) => job.feature.featureId === input.feature.featureId
      && job.feature.revision === input.feature.revision
      && job.feature.lineDigest === input.feature.lineDigest)
    .sort(newestFirst);
  // 같은 날짜가 겹치면 자료 참조 끝자리로 구분한다(날짜 선택지와 같은 규칙).
  const seen = new Map<string, number>();
  for (const asset of input.assets) seen.set(asset.label, (seen.get(asset.label) ?? 0) + 1);
  const named = input.assets.map((asset) => ({
    assetRef: asset.assetRef,
    label: (seen.get(asset.label) ?? 0) > 1 ? `${asset.label} · #${asset.assetRef.slice(-4)}` : asset.label,
  }));
  return named.map((asset) => {
    const mine = exact.filter((job) => job.assetRef === asset.assetRef);
    // 진행 중인 작업이 있으면 그것이 먼저다(중복 요청을 막는다). 그다음 가장 최근 작업.
    const active = mine.find((job) => job.executionState === "QUEUED" || job.executionState === "RUNNING");
    const completed = mine.find((job) => job.executionState === "COMPLETED");
    const chosen = active ?? completed ?? mine[0];
    if (!chosen) return { assetRef: asset.assetRef, label: asset.label, state: "none", jobId: null, reason: null };
    if (active) return { assetRef: asset.assetRef, label: asset.label, state: "active", jobId: active.jobId, reason: null };
    if (completed) {
      return completed.availability === "AVAILABLE"
        ? { assetRef: asset.assetRef, label: asset.label, state: "done", jobId: completed.jobId, reason: null }
        : { assetRef: asset.assetRef, label: asset.label, state: "unavailable", jobId: completed.jobId, reason: completed.availability };
    }
    return {
      assetRef: asset.assetRef,
      label: asset.label,
      state: chosen.executionState === "CANCELED" ? "canceled" : "failed",
      jobId: chosen.jobId,
      reason: chosen.reason ?? null,
    };
  });
}

export function hasActiveRequest(rows: readonly RequestRow[]): boolean {
  return rows.some((row) => row.state === "active");
}

export interface ProfileRequestBody {
  assetRef: string;
  feature: MeasurementFeatureRef;
  /** Re-read at an explicitly chosen existing plan spacing; omitted for the default plan. */
  sampleSpacingM?: number;
}

const ASSET_REF = /^ksa-v1-[0-9a-f]{64}$/;
const FEATURE_ID = /^mf-[0-9a-f]{32}$/;
const DIGEST = /^sha256:[0-9a-f]{64}$/;

/** 브라우저가 보낸 단면 요청 본문의 형식 검사. 판정 식별자는 받지 않는다 — BFF가 자료 참조로 Core에서 얻는다. */
export function parseProfileRequestBody(value: unknown): ProfileRequestBody | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const body = value as Record<string, unknown>;
  if (Object.keys(body).some((key) => key !== "assetRef" && key !== "feature" && key !== "sampleSpacingM")) return null;
  if (typeof body.assetRef !== "string" || !ASSET_REF.test(body.assetRef)) return null;
  const feature = body.feature;
  if (typeof feature !== "object" || feature === null || Array.isArray(feature)) return null;
  const ref = feature as Record<string, unknown>;
  if (Object.keys(ref).some((key) => !["featureId", "revision", "lineDigest"].includes(key))) return null;
  if (typeof ref.featureId !== "string" || !FEATURE_ID.test(ref.featureId)) return null;
  if (!Number.isSafeInteger(ref.revision) || (ref.revision as number) < 1 || (ref.revision as number) > 100) return null;
  if (typeof ref.lineDigest !== "string" || !DIGEST.test(ref.lineDigest)) return null;
  if (body.sampleSpacingM !== undefined && (typeof body.sampleSpacingM !== "number" || !Number.isFinite(body.sampleSpacingM) || body.sampleSpacingM <= 0)) return null;
  return {
    assetRef: body.assetRef,
    feature: { featureId: ref.featureId, revision: ref.revision as number, lineDigest: ref.lineDigest },
    ...(typeof body.sampleSpacingM === "number" ? { sampleSpacingM: body.sampleSpacingM } : {}),
  };
}
