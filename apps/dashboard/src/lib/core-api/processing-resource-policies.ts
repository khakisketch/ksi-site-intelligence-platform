import "server-only";

import { coreFetch } from "./client";
import type { ProcessingResourcePolicyListView } from "./types";

/**
 * Core가 발급한 읽기 전용 자원 입장 정책 목록. 정책 선택·한도 변경 표면은 없다.
 * 페이지는 이 읽기를 다른 부가 정보와 병렬로 시작하고, 현재 정책을 못 확인하면
 * 새 재구성 발급만 fail-closed 한다(ADR-KSI-032 D5, INV-055).
 */
export async function listProcessingResourcePolicies(): Promise<ProcessingResourcePolicyListView> {
  return coreFetch<ProcessingResourcePolicyListView>("/v1/processing-resource-policies");
}
