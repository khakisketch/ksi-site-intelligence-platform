import "server-only";

import { coreFetch } from "./client";
import type {
  DesignConformanceListView,
  DesignConformanceRequestCreateInput,
  DesignConformanceRequestListResponse,
  DesignConformanceRequestMutationResponse,
  DesignProgressResponse,
  DesignSurfaceListResponse,
  DesignSurfaceRegisterInput,
  DesignSurfaceRegisterResponse,
  DesignSurfaceSealResponse,
  DiffRasterViewResponse,
  ProgressBaselineResponse,
} from "./types";

/**
 * 설계 기준면 · 설계 대비 잔량(M4-A) 읽기·제출 클라이언트.
 *
 * `comparison.ts` 와 같은 규율이다 — **판정을 여기 두지 않는다.** 어떤 설계면이
 * 비교에 쓸 수 있는지(`VERIFIED` 만), 관측이 선언과 맞는지, 수직기준 계열이
 * 호환되는지는 전부 Core 가 정해서 내려주는 값이고, 화면이 스스로 판단하면 같은
 * 규칙이 두 곳에 생긴다.
 */

/**
 * 그 현장의 설계 기준면 목록 — 선언·관측·상태·거부 사유가 그대로 실려 온다.
 *
 * 미검증 상태를 걸러내지 않는 것이 요점이다: 화면이 "무엇이 주장이고 무엇이
 * 확인된 사실인가"를 그리려면 두 블록이 다 보여야 한다.
 */
export async function listDesignSurfaces(siteId: string): Promise<DesignSurfaceListResponse> {
  return coreFetch<DesignSurfaceListResponse>(
    `/v1/sites/${encodeURIComponent(siteId)}/design-surfaces`,
  );
}

/**
 * 설계면 등록 — 선언을 기록하고 업로드용 presigned PUT 을 발급받는다.
 *
 * 201 은 "파일이 좋다"가 아니라 "어디에 올리면 되는지 정해졌다"는 뜻이다.
 * 바이트는 대시보드 서버를 거치지 않는다(ADR-KSI-010 §1) — 브라우저가
 * `uploadUrl` 로 스토리지에 직접 PUT 한다.
 */
export async function registerDesignSurface(
  siteId: string,
  input: DesignSurfaceRegisterInput,
): Promise<DesignSurfaceRegisterResponse> {
  return coreFetch<DesignSurfaceRegisterResponse>(
    `/v1/sites/${encodeURIComponent(siteId)}/design-surfaces`,
    { method: "POST", body: input },
  );
}

/**
 * 봉인 — **업로드 완료 "주장"을 기록**하고 검증 대기 큐에 넣는다.
 *
 * Core 는 여기서 스토리지 바이트를 한 번도 읽지 않는다. 그래서 이 호출의
 * 성공은 "파일이 거기 있다"를 뜻하지 않는다 — 화면이 이 응답을 "완료"로
 * 부르면 안 되는 이유다(labels.ts `DESIGN_SURFACE_STATUS_LABEL.SEALED`).
 */
export async function sealDesignSurface(
  siteId: string,
  designSurfaceId: string,
): Promise<DesignSurfaceSealResponse> {
  return coreFetch<DesignSurfaceSealResponse>(
    `/v1/sites/${encodeURIComponent(siteId)}/design-surfaces/${encodeURIComponent(designSurfaceId)}/seal`,
    { method: "POST" },
  );
}

/**
 * "이 설계면과 이 지형을 비교하라" 제출.
 *
 * 같은 (설계면, 현재 작업, 구역) 조합의 재요청은 새 요청을 만들지 않고 기존
 * 것을 그대로 돌려준다(`ALREADY_REQUESTED`) — 호출부가 이를 오류가 아니라
 * 재사용으로 다뤄야 한다(`createComparisonRequest` 와 같은 규약).
 */
export async function createDesignConformanceRequest(
  missionId: string,
  input: DesignConformanceRequestCreateInput,
): Promise<DesignConformanceRequestMutationResponse> {
  return coreFetch<DesignConformanceRequestMutationResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/design-conformance-requests`,
    { method: "POST", body: input },
  );
}

/**
 * 그 임무의 설계 대비 요청 이력(최신 먼저).
 *
 * 요청 1건 조회 표면은 Core 에 없다 — 폴링도 이 목록을 읽고 requestId 로
 * 찾는다(요청 수가 임무당 한 자리라 목록 조회가 곧 단건 조회다).
 */
export async function listDesignConformanceRequests(
  missionId: string,
): Promise<DesignConformanceRequestListResponse> {
  return coreFetch<DesignConformanceRequestListResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/design-conformance-requests`,
  );
}

/**
 * 그 임무의 설계 대비 잔량 리포트 이력(최신 먼저).
 *
 * 404 는 오류가 아니라 "아직 계산되지 않음"이다 — 빈 목록과 구분하기 위해
 * 서버가 그렇게 답한다(`getVolumeChanges` 와 같은 규약).
 */
export async function getDesignConformance(
  missionId: string,
  limit?: number,
): Promise<DesignConformanceListView> {
  return coreFetch<DesignConformanceListView>(
    `/v1/missions/${encodeURIComponent(missionId)}/design-conformance`,
    { query: { limit: limit?.toString() } },
  );
}

/**
 * 저장된 차분 래스터의 단기 열람 URL — **지도는 반드시 이 경로로만** 얻는다.
 *
 * 브라우저가 설계면과 DSM 을 받아 다시 차분하는 경로를 만들지 않는 이유가 이
 * 함수의 존재 이유다: 그러면 지도와 표가 서로 다른 두 진실을 갖게 되고, 그
 * 어긋남은 어느 화면에서도 보이지 않는다.
 */
export async function getDiffRasterView(
  missionId: string,
  designConformanceId: string,
): Promise<DiffRasterViewResponse> {
  return coreFetch<DiffRasterViewResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/design-conformance/${encodeURIComponent(designConformanceId)}/diff-raster`,
  );
}

/**
 * 이 리포트를 "원지형 기준"으로 지정한다 — 계획 물량이 여기서 나온다(M4-C).
 *
 * 자동으로 고르지 않는 이유가 이 호출의 존재 이유다. 가장 오래된 리포트를
 * 기준으로 삼으면, 첫 비행이 이미 시공 중이었을 때 계획 물량이 조용히 깎인다.
 * 덮어쓸 수 있다 — 잘못 지정하는 일이 실제로 있다.
 */
export async function setProgressBaseline(
  missionId: string,
  designConformanceId: string,
  designSurfaceId: string,
): Promise<ProgressBaselineResponse> {
  return coreFetch<ProgressBaselineResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/design-conformance/${encodeURIComponent(designConformanceId)}/progress-baseline`,
    { method: "POST", body: { designSurfaceId } },
  );
}

/**
 * 구역별 계획·완료·잔여·진척률(M4-C) — **저장된 값이 아니라 파생값**이다.
 *
 * 200 이 항상 성공을 뜻하지 않는다 — `progress` 와 `detail` 중 하나는 항상
 * 채워진다("아직 데이터가 없다"와 "이어붙일 수 없다"를 화면이 갈라 말해야
 * 해서다). 호출부는 반드시 `progress` 의 존재로 분기해야 한다.
 */
export async function getDesignProgress(
  siteId: string,
  designSurfaceId: string,
): Promise<DesignProgressResponse> {
  return coreFetch<DesignProgressResponse>(
    `/v1/sites/${encodeURIComponent(siteId)}/design-progress`,
    { query: { design_surface_id: designSurfaceId } },
  );
}
