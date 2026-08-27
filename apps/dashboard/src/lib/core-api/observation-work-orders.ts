import "server-only";

import { coreFetch } from "./client";
import type {
  ObservationWorkOrderView,
  ReobservationDraftView,
  TemporalCoherencePolicy,
} from "./types";

export interface CreateObservationWorkOrderInput {
  name: string;
  workAreaIds: string[];
  scheduleId?: string | null;
  temporalPolicy?: TemporalCoherencePolicy | null;
}

/**
 * 현장 작업 원장은 Core가 소유한다. Dashboard는 사람이 만든 초안만 전달하며,
 * work area 존재·조직 경계·허용 전이는 Core가 판단한 결과를 그대로 받는다.
 */
export async function createObservationWorkOrder(
  siteId: string,
  input: CreateObservationWorkOrderInput,
): Promise<ObservationWorkOrderView> {
  return coreFetch<ObservationWorkOrderView>(
    `/v1/sites/${encodeURIComponent(siteId)}/observation-work-orders`,
    { method: "POST", body: input },
  );
}

export async function listObservationWorkOrders(
  siteId: string,
): Promise<ObservationWorkOrderView[]> {
  const response = await coreFetch<{ workOrders: ObservationWorkOrderView[] }>(
    `/v1/sites/${encodeURIComponent(siteId)}/observation-work-orders`,
  );
  return response.workOrders;
}

export type WorkOrderActionGroup = "DECISION_REQUIRED" | "IN_PROGRESS" | "COMPLETED";

/** 조직 범위의 전역 작업 큐. Core가 organization scope를 먼저 적용한 뒤 필터링한다. */
export async function listObservationWorkOrdersForOrganization(filters: {
  siteId?: string;
  status?: string;
  actionGroup?: WorkOrderActionGroup;
} = {}): Promise<ObservationWorkOrderView[]> {
  const response = await coreFetch<{ workOrders: ObservationWorkOrderView[] }>(
    "/v1/observation-work-orders",
    { query: filters },
  );
  return response.workOrders;
}

export async function getObservationWorkOrder(
  workOrderId: string,
): Promise<ObservationWorkOrderView> {
  return coreFetch<ObservationWorkOrderView>(
    `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}`,
  );
}

export async function approveObservationWorkOrder(
  workOrderId: string,
  expectedVersion: number,
): Promise<ObservationWorkOrderView> {
  return coreFetch<ObservationWorkOrderView>(
    `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/approve`,
    { method: "POST", body: { expectedVersion } },
  );
}

export async function listReobservationDrafts(
  workOrderId: string,
): Promise<ReobservationDraftView[]> {
  const response = await coreFetch<{ drafts: ReobservationDraftView[] }>(
    `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/reobservation-drafts`,
  );
  return response.drafts;
}

export async function approveReobservationDraft(
  draftId: string,
  expectedVersion: number,
): Promise<ReobservationDraftView> {
  return coreFetch<ReobservationDraftView>(
    `/v1/reobservation-drafts/${encodeURIComponent(draftId)}/approve`,
    { method: "POST", body: { expectedVersion } },
  );
}
