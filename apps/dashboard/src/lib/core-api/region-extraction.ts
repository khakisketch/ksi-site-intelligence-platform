import "server-only";

import { coreFetch } from "./client";
import type { RegionExtractionEntry, RegionExtractionListView, SpatialRefreshDraftResponse } from "./types";

/**
 * 변화 영역 자동 추출(M4-E) 읽기 클라이언트 — 판정 로직을 두지 않는다.
 *
 * 이 파일이 하는 일은 서버 응답을 그대로 옮기는 것뿐이다: 어느 영역이 재관찰
 * 대상인지, hull이 유효한지는 전부 서버가 이미 계산해 실어 보낸다
 * (`comparison.ts` 모듈 docstring과 같은 원칙).
 */

/** 그 임무의 변화 영역 추출 이력(최신 우선) — 계산된 적이 없으면 404. */
export async function listRegionExtraction(missionId: string): Promise<RegionExtractionListView> {
  return coreFetch<RegionExtractionListView>(
    `/v1/missions/${encodeURIComponent(missionId)}/region-extraction`,
  );
}

/** 변화 영역 추출 리포트 1건. */
export async function getRegionExtraction(
  missionId: string,
  changeRegionSetId: string,
): Promise<RegionExtractionEntry> {
  return coreFetch<RegionExtractionEntry>(
    `/v1/missions/${encodeURIComponent(missionId)}/region-extraction/${encodeURIComponent(changeRegionSetId)}`,
  );
}

/**
 * 이 영역의 재관찰 AOI 초안 — **임무를 발급하지 않는다**. 사람이 검토한 뒤
 * 그 AOI로 SurveyWizard를 통해 직접 발급해야 한다(서버 모듈 docstring).
 */
export async function getSpatialRefreshDraft(
  missionId: string,
  changeRegionSetId: string,
  regionId: string,
): Promise<SpatialRefreshDraftResponse> {
  return coreFetch<SpatialRefreshDraftResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/region-extraction/` +
      `${encodeURIComponent(changeRegionSetId)}/regions/${encodeURIComponent(regionId)}/spatial-refresh-draft`,
  );
}
