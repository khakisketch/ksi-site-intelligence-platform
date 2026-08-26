import "server-only";

import { coreFetch } from "./client";
import type {
  AoiVertex,
  DataResidency,
  SiteFrame,
  SiteDetailView,
  SiteStatus,
  SiteView,
  SpatialModelView,
} from "./types";

export async function listSites(): Promise<SiteView[]> {
  const body = await coreFetch<{ sites: SiteView[] }>("/v1/sites");
  return body.sites;
}

export async function getSite(siteId: string): Promise<SiteDetailView> {
  return coreFetch<SiteDetailView>(`/v1/sites/${encodeURIComponent(siteId)}`);
}

/**
 * 이 현장에 공간모델이 있는가·낡았는가(ADR-KSI-019 G1).
 *
 * 서버가 매 호출 재계산하는 파생 판정이라 대시보드가 캐시하거나 재계산하지 않는다.
 * 재구성 원장이 없는 조립에서는 이 표면 자체가 없다(404) — 그때 화면은 "모델 없음"이
 * 아니라 "확인할 수 없음"으로 다뤄야 한다.
 */
export async function getSpatialModel(siteId: string): Promise<SpatialModelView> {
  return coreFetch<SpatialModelView>(
    `/v1/sites/${encodeURIComponent(siteId)}/spatial-model`,
  );
}

export interface SetModelAgePolicyInput {
  /** null 이면 철회 — 철회하면 서버가 노후를 판정하지 않는다. */
  maxAgeDays: number | null;
}

/** 이 현장의 공간모델 노후 판정 기준(일)을 선언·교체·철회한다. */
export async function setSiteModelAgePolicy(
  siteId: string,
  input: SetModelAgePolicyInput,
): Promise<SiteView> {
  const body = await coreFetch<{ site: SiteView }>(
    `/v1/sites/${encodeURIComponent(siteId)}/model-age-policy`,
    { method: "PUT", body: input },
  );
  return body.site;
}

export interface RegisterSiteInput {
  siteId: string;
  name: string;
  siteFrame: SiteFrame;
  /** 선택 — 생략하면 등록 후 setSiteAoi 로 나중에 설정한다(UNMAPPED 상태에서만). */
  aoi?: { vertices: AoiVertex[] };
  /**
   * 선택 — 생략은 반출 불가를 뜻한다(INV-050, 관대한 기본값 아님). 등록 이후
   * 변경 경로는 의도적으로 없다 — 반출 허용은 법적 판단이라 SITES_WRITE 로
   * 조용히 바꿀 값이 아니다(contracts/api/openapi-core.yaml dataResidency 설명).
   */
  dataResidency?: DataResidency;
  /** 외부 AI provider 호출의 별도 명시 동의. 생략/false는 호출 거부다. */
  aiEgressAllowed?: boolean;
}

export async function registerSite(input: RegisterSiteInput): Promise<SiteView> {
  const body = await coreFetch<{ site: SiteView }>("/v1/sites", {
    method: "POST",
    body: input,
  });
  return body.site;
}

export interface SetSiteAoiInput {
  aoi: { vertices: AoiVertex[] };
  /** 등록된 현장의 것과 정확 일치해야 한다(SITE_FRAME_MISMATCH). */
  siteFrame: SiteFrame;
}

/** UNMAPPED 상태의 현장에만 AOI 를 설정·교체한다(그 외 상태는 409 AOI_LOCKED). */
export async function setSiteAoi(siteId: string, input: SetSiteAoiInput): Promise<SiteView> {
  const body = await coreFetch<{ site: SiteView }>(
    `/v1/sites/${encodeURIComponent(siteId)}/aoi`,
    { method: "PUT", body: input },
  );
  return body.site;
}

export interface TransitionSiteInput {
  targetStatus: SiteStatus;
  evidence: string;
  reason: string;
}

export async function transitionSite(siteId: string, input: TransitionSiteInput): Promise<SiteView> {
  const body = await coreFetch<{ site: SiteView }>(
    `/v1/sites/${encodeURIComponent(siteId)}/transitions`,
    { method: "POST", body: input },
  );
  return body.site;
}
