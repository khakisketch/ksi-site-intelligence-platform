import "server-only";

import { coreFetch, coreFetchBinary, type CoreBinaryResponse } from "./client";
import type {
  CoverageReportView,
  MissionExecutionStatus,
  MissionExecutionView,
  MissionRecordResponse,
} from "./types";

export async function listMissions(siteId?: string): Promise<MissionRecordResponse[]> {
  return coreFetch<MissionRecordResponse[]>("/v1/missions", { query: { siteId } });
}

export async function getMission(missionId: string): Promise<MissionRecordResponse> {
  return coreFetch<MissionRecordResponse>(`/v1/missions/${encodeURIComponent(missionId)}`);
}

/**
 * 발급된 임무의 KMZ 바이트 — Core 가 저장된 요청으로 매 조회마다 재생성해 돌려준다
 * (바이트 자체는 저장하지 않는다). 산출물이 없거나(계약 단독) 더 이상 재현할 수
 * 없으면 Core 가 404/409 를 주고, 이는 ``CoreApiError`` 로 전파된다.
 */
export async function getMissionKmz(missionId: string): Promise<CoreBinaryResponse> {
  return coreFetchBinary(`/v1/missions/${encodeURIComponent(missionId)}/kmz`);
}

/**
 * 그 임무의 **최신** 비행 후 커버리지 보고 — 완료 판정의 권위(INV-010, PRD §15.5).
 * 아직 보고가 도착하지 않았으면 Core 가 404 를 주고, 이는 ``CoreApiError`` 로
 * 전파된다(호출부가 "아직 보고 없음" 빈 상태로 구분해서 처리한다).
 */
export async function getCoverageReport(missionId: string): Promise<CoverageReportView> {
  return coreFetch<CoverageReportView>(
    `/v1/missions/${encodeURIComponent(missionId)}/coverage-report`,
  );
}

/**
 * 그 임무의 실행 생애주기(ADR-KSI-019 G2) — 발급 이후 무슨 일이 있었는가.
 *
 * 전이가 한 번도 없었으면 status 는 `ISSUED` 이고 history 는 빈 배열이다
 * (레코드 부재 = ISSUED). 이 값은 **완료 판정의 권위가 아니라 CoverageReport
 * 원장의 투영**이므로(INV-010), 화면이 완료를 단정할 때는 커버리지 보고를 근거로
 * 삼는다. 실행 상태 표면이 없는 조립에서는 404 이고 `CoreApiError` 로 전파된다.
 */
export async function getMissionExecution(missionId: string): Promise<MissionExecutionView> {
  return coreFetch<MissionExecutionView>(
    `/v1/missions/${encodeURIComponent(missionId)}/execution`,
  );
}

export interface MissionExecutionTransitionInput {
  targetStatus: MissionExecutionStatus;
  detail?: string | null;
}

/**
 * 실행 상태를 사람이 선언한다 — Core 는 `DISPATCHED`·`CANCELLED` 만 사람 선언으로
 * 받는다(mission_execution.py `_HUMAN_DECLARABLE`). 그 외 대상 상태나 권한 없는
 * 요청은 403 이고, 현재 상태에서 허용되지 않는 전이는 409 다 — 둘 다 `CoreApiError`
 * 로 전파된다. 현장 화면의 [수동 이관 신고] 버튼이 이 함수를 부른다.
 */
export async function declareMissionExecutionTransition(
  missionId: string,
  input: MissionExecutionTransitionInput,
): Promise<MissionExecutionView> {
  return coreFetch<MissionExecutionView>(
    `/v1/missions/${encodeURIComponent(missionId)}/execution-transitions`,
    { method: "POST", body: input },
  );
}
