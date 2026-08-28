import "server-only";

import { coreFetch } from "./client";
import type {
  CivilComparisonPreflightResponse,
  ComparisonPolicyView,
  ComparisonRequestCreateInput,
  ComparisonRequestDetailView,
  ComparisonRequestListResponse,
  ComparisonRequestMutationResponse,
  SiteProcessingJobListResponse,
} from "./types";

/**
 * 두 시점 비교(W2) 읽기·제출 클라이언트.
 *
 * 이 파일에 판정 로직을 두지 않는다 — `changeDetectionEligible`/
 * `volumeChangeEligible`·상태 전이·멱등 재요청(ALREADY_REQUESTED)은 전부 서버가
 * 정해서 내려주는 값이고, 화면이 스스로 판단하면 같은 규칙이 두 곳에 생긴다
 * (`phase34.ts` 모듈 docstring 과 같은 원칙).
 */

/**
 * 그 현장의 재구성 epoch 목록(최신 먼저) — 비교 후보를 고르는 입력.
 *
 * 임무별 목록과 같은 서버 모델이라 `artifacts` 가 함께 온다: 화면이 "이 epoch 에
 * 점군·높이자료가 있는가"를 산출물마다 다시 묻지 않고 이 응답 하나로 판단한다.
 */
export async function listSiteProcessingJobs(
  siteId: string,
  limit?: number,
): Promise<SiteProcessingJobListResponse> {
  return coreFetch<SiteProcessingJobListResponse>(
    `/v1/sites/${encodeURIComponent(siteId)}/processing-jobs`,
    { query: { limit: limit?.toString() } },
  );
}

/**
 * 이 배포가 실제 계산에 쓰는 고정 기준값 — **표시 전용**.
 *
 * 화면에 숫자를 복제하지 않기 위해 서버에서 받는다(그 모듈 docstring). 사용자가
 * 이 값을 바꾸는 표면은 없다(대표자 확정).
 */
export async function getComparisonPolicy(): Promise<ComparisonPolicyView> {
  return coreFetch<ComparisonPolicyView>("/v1/comparison-policy");
}

/**
 * "이 두 작업을 비교하라" 제출.
 *
 * 같은 조합의 재요청은 새 요청을 만들지 않고 기존 것을 그대로 돌려준다
 * (`ALREADY_REQUESTED`) — 호출부가 이를 오류가 아니라 재사용으로 다뤄야 한다
 * (`issueProcessingJob` 의 `ALREADY_ISSUED` 와 같은 규약).
 */
export async function createComparisonRequest(
  missionId: string,
  input: ComparisonRequestCreateInput,
): Promise<ComparisonRequestMutationResponse> {
  return coreFetch<ComparisonRequestMutationResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/comparison-requests`,
    { method: "POST", body: input },
  );
}

/**
 * Ask Core whether the selected epochs are safe for a quantitative comparison.
 * This is intentionally a separate read-like command: it creates no request
 * and returns INV-053's typed blocker verbatim for the Console to explain.
 */
export async function preflightComparisonRequest(
  missionId: string,
  input: ComparisonRequestCreateInput,
): Promise<CivilComparisonPreflightResponse> {
  return coreFetch<CivilComparisonPreflightResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/comparison-preflight`,
    { method: "POST", body: input },
  );
}

/** 그 임무의 비교 요청 이력(최신 먼저) — 새로고침 후 상태 복원에 쓴다. */
export async function listComparisonRequests(
  missionId: string,
): Promise<ComparisonRequestListResponse> {
  return coreFetch<ComparisonRequestListResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/comparison-requests`,
  );
}

/** 비교 요청 1건 — 폴링이 이 표면을 5초마다 두드린다. */
export async function getComparisonRequest(
  requestId: string,
): Promise<ComparisonRequestDetailView> {
  return coreFetch<ComparisonRequestDetailView>(
    `/v1/comparison-requests/${encodeURIComponent(requestId)}`,
  );
}
