import "server-only";

import { coreFetch } from "./client";
import type {
  ArtifactDownloadResponse,
  ChangeDetectionView,
  DefectCandidateListView,
  EquipmentStateListView,
  EquipmentSupportListView,
  EquipmentSupportView,
  ProcessingJobArtifactsView,
  RiskAssessmentView,
  SourceMediaViewResponse,
  VolumeChangeListView,
} from "./types";

/**
 * Phase 3/4 읽기 클라이언트 — 결함 후보·변화 탐지·장비 상태·지원단계.
 *
 * 이 파일에 판정 로직을 두지 않는다. `productionSupported`·`revisitRecommended`·
 * `reobservationRecommended` 는 전부 서버가 계산해서 내려주는 값이고, 화면이
 * `state` 문자열이나 비율을 보고 스스로 판단하면 같은 규칙이 두 곳에 생긴다 —
 * 그 갈라짐은 화면에서 보이지 않는다(coverage.ts 가 비율을 재계산하지 않는 것과
 * 같은 원칙).
 */

/** 그 임무의 결함 후보. 0건은 404 가 아니라 빈 목록이다. */
export async function listDefectCandidates(
  missionId: string,
  sourceMediaId?: string,
): Promise<DefectCandidateListView> {
  return coreFetch<DefectCandidateListView>(
    `/v1/missions/${encodeURIComponent(missionId)}/defect-candidates`,
    { query: { sourceMediaId } },
  );
}

/**
 * 그 임무의 **최신** 변화 탐지 결과 + 재방문 권고(PRD §15.2 ⑤).
 *
 * `revisitRatioThreshold` 는 정책 값이라 서버가 지어내지 않는다 — 생략하면 서버의
 * 화면 초기값이 쓰이고, 응답이 실제로 쓴 값을 되돌려준다. 결과가 아직 없으면
 * Core 가 404 를 주고 `CoreApiError` 로 전파된다(호출부가 빈 상태로 구분한다).
 */
export async function getChangeDetection(
  missionId: string,
  revisitRatioThreshold?: number,
): Promise<ChangeDetectionView> {
  return coreFetch<ChangeDetectionView>(
    `/v1/missions/${encodeURIComponent(missionId)}/change-detection`,
    { query: { revisitRatioThreshold: revisitRatioThreshold?.toString() } },
  );
}

/**
 * 그 임무의 체적 변화 리포트 이력(최신 우선).
 *
 * 404 는 오류가 아니라 "아직 계산되지 않음"이다 — 빈 목록과 구분하기 위해
 * 서버가 그렇게 답한다(`getChangeDetection` 과 같은 규약).
 */
export async function getVolumeChanges(
  missionId: string,
  limit?: number,
): Promise<VolumeChangeListView> {
  return coreFetch<VolumeChangeListView>(
    `/v1/missions/${encodeURIComponent(missionId)}/volume-changes`,
    { query: { limit: limit?.toString() } },
  );
}

/**
 * 재구성 작업 1건의 산출물 목록 — 정사영상처럼 체적 리포트가 참조하지 않는
 * 산출물(kind 로 구분)을 찾을 때 쓴다. `VolumeChangeReport.current.jobId` 가
 * 이미 같은 작업을 가리키므로, 화면은 이 조회 하나로 "그 epoch 에 정사영상이
 * 있는가"를 판단한다.
 */
export async function getProcessingJobArtifacts(jobId: string): Promise<ProcessingJobArtifactsView> {
  return coreFetch<ProcessingJobArtifactsView>(
    `/v1/processing-jobs/${encodeURIComponent(jobId)}`,
  );
}

/**
 * 등록된 산출물 1건의 단기 다운로드 URL. `verdict !== "ARTIFACT_READY"` 면
 * `downloadUrl` 이 null 이다 — 호출부가 그 경우를 빈 상태로 다뤄야 한다
 * (`getEvidenceViewUrl` 과 같은 규약).
 */
export async function getProcessingArtifactDownloadUrl(
  jobId: string,
  artifactId: string,
): Promise<ArtifactDownloadResponse> {
  return coreFetch<ArtifactDownloadResponse>(
    `/v1/processing-jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactId)}/download`,
  );
}

/** 그 현장의 개체별 **최신** 운동상태(이력이 아니라 현재 스냅샷). */
export async function listEquipmentStates(siteId: string): Promise<EquipmentStateListView> {
  return coreFetch<EquipmentStateListView>(
    `/v1/sites/${encodeURIComponent(siteId)}/equipment-states`,
  );
}

/**
 * 지목한 두 개체의 CPA/TTC + 재관찰 권고.
 *
 * 쌍과 정책 파라미터를 **전부 호출자가 지목한다** — "어느 쌍이 평가 대상인가"는
 * 서버가 정하지 않는다. 두 상태의 관측 시각차가 `maxObservationGapS` 를 넘으면
 * Core 가 422 를 준다: 그건 "위험 없음"이 아니라 **계산 불가**다.
 */
export async function assessRisk(
  siteId: string,
  params: {
    equipmentEntityId: string;
    subjectEntityId: string;
    horizonS: number;
    combinedRadiusM: number;
    maxObservationGapS: number;
    positionUncertaintyThresholdM: number;
  },
): Promise<RiskAssessmentView> {
  return coreFetch<RiskAssessmentView>(
    `/v1/sites/${encodeURIComponent(siteId)}/risk-assessment`,
    {
      query: {
        equipmentEntityId: params.equipmentEntityId,
        subjectEntityId: params.subjectEntityId,
        horizonS: params.horizonS.toString(),
        combinedRadiusM: params.combinedRadiusM.toString(),
        maxObservationGapS: params.maxObservationGapS.toString(),
        positionUncertaintyThresholdM: params.positionUncertaintyThresholdM.toString(),
      },
    },
  );
}

/** 등록된 장비 클래스 전체 + 지원단계(MASTER_PRD §23.3/§26.7). */
export async function listEquipmentSupport(): Promise<EquipmentSupportListView> {
  return coreFetch<EquipmentSupportListView>("/v1/equipment-support");
}

export async function getEquipmentSupport(classId: string): Promise<EquipmentSupportView> {
  return coreFetch<EquipmentSupportView>(
    `/v1/equipment-support/${encodeURIComponent(classId)}`,
  );
}

/**
 * 사진 1장의 단기 열람 URL + 원장이 아는 화소수.
 *
 * 화소수를 서버가 함께 내는 이유는 결함 후보 폴리곤이 **원본 픽셀 좌표**이기
 * 때문이다 — 화면이 축소해 그릴 때 배율을 계산하려면 원본 크기가 필요하고, 그 값을
 * 이미지 로드 후에 읽으면 로드 전에 레이아웃을 잡을 수 없다.
 *
 * 객체가 아직 업로드되지 않았어도 URL 은 발급된다(등록과 업로드는 별개 단계다).
 */
export async function getSourceMediaView(
  missionId: string,
  mediaId: string,
): Promise<SourceMediaViewResponse> {
  return coreFetch<SourceMediaViewResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/source-media/${encodeURIComponent(mediaId)}/view`,
  );
}
