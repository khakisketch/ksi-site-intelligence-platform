import "server-only";

import { coreFetch } from "./client";
import type {
  ProcessingJobIssueInput,
  ProcessingJobListSummary,
  ProcessingJobMutationResponse,
} from "./types";

/**
 * 처리 작업 발급 — 입력(장수·화소 합·sourceBundleDigest)은 여기 없다. 봉인된
 * 번들이 정하고 Core 가 집계한다(B2, JobSpec 모듈 docstring). 같은 사양의
 * 재요청은 새 작업을 만들지 않고 기존 작업을 ``ALREADY_ISSUED`` 로 돌려준다 —
 * 호출부가 이를 오류가 아니라 재사용으로 다뤄야 한다.
 */
export async function issueProcessingJob(
  missionId: string,
  spec: ProcessingJobIssueInput,
): Promise<ProcessingJobMutationResponse> {
  return coreFetch<ProcessingJobMutationResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/processing-jobs`,
    { method: "POST", body: spec },
  );
}

/** 그 임무에 발급된 처리 작업 이력(최신 포함) — 페이지 새로고침 후 상태 복원에 쓴다. */
export async function listProcessingJobs(missionId: string): Promise<ProcessingJobListSummary> {
  return coreFetch<ProcessingJobListSummary>(
    `/v1/missions/${encodeURIComponent(missionId)}/processing-jobs`,
  );
}
