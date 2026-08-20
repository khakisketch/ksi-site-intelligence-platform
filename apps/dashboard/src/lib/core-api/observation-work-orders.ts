import "server-only";

import { coreFetch } from "./client";
import type {
  ObservationWorkOrderView,
  ReobservationDraftView,
} from "./types";

export async function listObservationWorkOrders(
  siteId: string,
): Promise<ObservationWorkOrderView[]> {
  const response = await coreFetch<{ workOrders: ObservationWorkOrderView[] }>(
    `/v1/sites/${encodeURIComponent(siteId)}/observation-work-orders`,
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
