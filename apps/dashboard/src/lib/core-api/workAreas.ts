import "server-only";

import { coreFetch } from "./client";
import type { WorkAreaListResponse, WorkAreaRegisterInput, WorkAreaResponse } from "./types";

/**
 * 현장의 작업구역(M4-C) 읽기·등록·보관 클라이언트.
 *
 * `design.ts` 와 같은 규율이다 — 판정을 여기 두지 않는다. 등록 시점 유효성(폴리곤
 * 모양·상한·중복 대체 대상)은 전부 Core 가 정해서 내려주는 verdict/detail 이고,
 * 화면은 그것을 그대로 옮긴다.
 */

/** 그 현장의 작업구역 목록. 기본은 고를 수 있는 것(ACTIVE)만 — 보관된 것을 보려면 명시한다. */
export async function listWorkAreas(
  siteId: string,
  options?: { includeArchived?: boolean },
): Promise<WorkAreaListResponse> {
  return coreFetch<WorkAreaListResponse>(`/v1/sites/${encodeURIComponent(siteId)}/work-areas`, {
    query: { include_archived: options?.includeArchived ? "true" : undefined },
  });
}

/**
 * 작업구역 등록 — **기하는 이 순간 굳는다.**
 *
 * 잘못 그렸으면 `supersedes` 로 새 구역을 등록한다(이전 것은 자동으로 보관된다).
 * 제자리 수정 API 는 없다 — 있으면 이미 그 구역으로 낸 리포트가 가리키는 범위가
 * 사후에 바뀐다.
 */
export async function registerWorkArea(
  siteId: string,
  input: WorkAreaRegisterInput,
): Promise<WorkAreaResponse> {
  return coreFetch<WorkAreaResponse>(`/v1/sites/${encodeURIComponent(siteId)}/work-areas`, {
    method: "POST",
    body: input,
  });
}

/**
 * 보관 — **삭제가 아니다.** 새 비교에 고를 수 없게 될 뿐, 이미 낸 리포트는 그대로
 * 남는다(그 리포트들이 zoneId 로 이 id 를 들고 있어서다).
 */
export async function archiveWorkArea(
  siteId: string,
  workAreaId: string,
): Promise<WorkAreaResponse> {
  return coreFetch<WorkAreaResponse>(
    `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/archive`,
    { method: "POST" },
  );
}
