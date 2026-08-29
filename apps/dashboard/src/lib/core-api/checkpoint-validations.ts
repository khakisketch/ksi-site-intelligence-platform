import "server-only";

import { coreFetch } from "./client";
import type {
  CheckpointValidationListResponse,
  CheckpointValidationMutationResponse,
  CheckpointValidationRegisterInput,
  CheckpointValidationRegisterResponse,
} from "./types";

/**
 * 한 DSM epoch 에 이미 봉인된 검사점 검증 이력. 이력은 읽기 전용이며, 페이지
 * 조립에서 실패해도 임무 상세 전체가 내려가지 않도록 호출부가 경계를 둔다.
 */
export async function listCheckpointValidations(
  jobId: string,
): Promise<CheckpointValidationListResponse> {
  return coreFetch<CheckpointValidationListResponse>(
    `/v1/processing-jobs/${encodeURIComponent(jobId)}/checkpoint-validations`,
  );
}

/** 검사점 CSV claim 등록; Core가 단기 PUT URL을 내리고 browser가 bytes를 직접 올린다. */
export async function registerCheckpointValidation(
  jobId: string,
  artifactId: string,
  input: CheckpointValidationRegisterInput,
): Promise<CheckpointValidationRegisterResponse> {
  return coreFetch<CheckpointValidationRegisterResponse>(
    `/v1/processing-jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactId)}/checkpoint-validations`,
    // `declared` marks these values as operator claims. It makes the boundary
    // explicit: the subsequent `observed` metrics can only be worker-produced.
    { method: "POST", body: { declared: input } },
  );
}

/** 업로드 완료를 봉인한다. 실제 digest/크기/DSM 측정은 이후 worker가 수행한다. */
export async function sealCheckpointValidation(
  validationId: string,
): Promise<CheckpointValidationMutationResponse> {
  return coreFetch<CheckpointValidationMutationResponse>(
    `/v1/checkpoint-validations/${encodeURIComponent(validationId)}/seal`,
    { method: "POST" },
  );
}

/** SEALED 동안만 폴링할 상세 projection. */
export async function getCheckpointValidation(
  validationId: string,
): Promise<CheckpointValidationMutationResponse> {
  return coreFetch<CheckpointValidationMutationResponse>(
    `/v1/checkpoint-validations/${encodeURIComponent(validationId)}`,
  );
}
