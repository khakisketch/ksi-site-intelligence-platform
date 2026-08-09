import "server-only";

import { coreFetch, coreFetchBinary, type CoreBinaryResponse } from "./client";
import type { CoverageReportView, MissionRecordResponse } from "./types";

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
