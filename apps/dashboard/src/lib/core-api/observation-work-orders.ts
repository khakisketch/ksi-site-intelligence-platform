import "server-only";

import { coreFetch, coreFetchWithToken } from "./client";
import type {
  ObservationWorkOrderView,
  ObservationWorkOrderOperationsView,
  ReobservationDraftView,
  TemporalCoherencePolicy,
} from "./types";

export interface CreateObservationWorkOrderInput {
  name: string;
  workAreaIds: string[];
  scheduleId?: string | null;
  temporalPolicy?: TemporalCoherencePolicy | null;
  executionMode?: "MANAGED_ACQUISITION" | "EXTERNAL_RECONSTRUCTION";
}

/**
 * 현장 작업 원장은 Core가 소유한다. Dashboard는 사람이 만든 초안만 전달하며,
 * work area 존재·조직 경계·허용 전이는 Core가 판단한 결과를 그대로 받는다.
 *
 * 같은 토큰으로 whoami와 생성을 잇는 연속성 검사 경로 전용 — 토큰을 두 번
 * 읽으면 검사와 변이 사이 세션 교체(TOCTOU)가 생긴다. 기존 호출부는 그대로 둔다.
 */
export async function createObservationWorkOrderWithToken(
  siteId: string,
  input: CreateObservationWorkOrderInput,
  idempotencyKey: string | undefined,
  token: string,
): Promise<ObservationWorkOrderView> {
  return coreFetchWithToken<ObservationWorkOrderView>(
    `/v1/sites/${encodeURIComponent(siteId)}/observation-work-orders`,
    token,
    {
      method: "POST",
      body: input,
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    },
  );
}

export async function createObservationWorkOrder(
  siteId: string,
  input: CreateObservationWorkOrderInput,
  idempotencyKey?: string,
): Promise<ObservationWorkOrderView> {
  return coreFetch<ObservationWorkOrderView>(
    `/v1/sites/${encodeURIComponent(siteId)}/observation-work-orders`,
    {
      method: "POST",
      body: input,
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    },
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

const operationsPath = (workOrderId: string) =>
  `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/operations`;

export async function getObservationWorkOrderOperations(
  workOrderId: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetch<ObservationWorkOrderOperationsView>(operationsPath(workOrderId));
}

export async function listObservationWorkOrderOperations(filters: {
  siteId?: string;
  workflowStatus?: "UNSPECIFIED" | "OPEN" | "CLOSED";
} = {}): Promise<ObservationWorkOrderOperationsView[]> {
  const response = await coreFetch<{ operations: ObservationWorkOrderOperationsView[] }>(
    "/v1/observation-work-order-operations",
    { query: filters },
  );
  return response.operations;
}

export async function assignObservationWorkOrderToMe(
  workOrderId: string,
  expectedOperationsRevision: number,
  action: "ASSIGN_TO_ME" | "CLEAR" | "ASSIGN_TO_MEMBER",
  idempotencyKey: string,
  assigneePrincipalId?: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetch<ObservationWorkOrderOperationsView>(`${operationsPath(workOrderId)}/assignment`, {
    method: "POST",
    body: action === "ASSIGN_TO_MEMBER"
      ? { expectedOperationsRevision, action, assigneePrincipalId }
      : { expectedOperationsRevision, action },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function setObservationWorkOrderDueDate(
  workOrderId: string,
  expectedOperationsRevision: number,
  dueAt: string | null,
  idempotencyKey: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetch<ObservationWorkOrderOperationsView>(`${operationsPath(workOrderId)}/due-date`, {
    method: "PUT",
    body: { expectedOperationsRevision, dueAt },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function closeObservationWorkOrder(
  workOrderId: string,
  expectedOperationsRevision: number,
  note: string | null,
  idempotencyKey: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetch<ObservationWorkOrderOperationsView>(`${operationsPath(workOrderId)}/close`, {
    method: "POST",
    body: { expectedOperationsRevision, note },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function reopenObservationWorkOrder(
  workOrderId: string,
  expectedOperationsRevision: number,
  idempotencyKey: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetch<ObservationWorkOrderOperationsView>(`${operationsPath(workOrderId)}/reopen`, {
    method: "POST",
    body: { expectedOperationsRevision },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

/**
 * 같은 요청의 세션 토큰 하나로 Core whoami 연속성 검사와 변이를 잇는 경로 전용 —
 * 토큰을 두 번 읽으면 검사와 변이 사이 세션 교체(TOCTOU)가 생긴다. 기존 호출부는 그대로 둔다.
 */
export async function assignObservationWorkOrderToMeWithToken(
  workOrderId: string,
  expectedOperationsRevision: number,
  action: "ASSIGN_TO_ME" | "CLEAR" | "ASSIGN_TO_MEMBER",
  idempotencyKey: string,
  token: string,
  assigneePrincipalId?: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetchWithToken<ObservationWorkOrderOperationsView>(`${operationsPath(workOrderId)}/assignment`, token, {
    method: "POST",
    body: action === "ASSIGN_TO_MEMBER"
      ? { expectedOperationsRevision, action, assigneePrincipalId }
      : { expectedOperationsRevision, action },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

/** 같은 요청의 세션 토큰 하나로 연속성 검사와 변이를 잇는 경로 전용. 기존 호출부는 그대로 둔다. */
export async function setObservationWorkOrderDueDateWithToken(
  workOrderId: string,
  expectedOperationsRevision: number,
  dueAt: string | null,
  idempotencyKey: string,
  token: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetchWithToken<ObservationWorkOrderOperationsView>(`${operationsPath(workOrderId)}/due-date`, token, {
    method: "PUT",
    body: { expectedOperationsRevision, dueAt },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

/** 같은 요청의 세션 토큰 하나로 연속성 검사와 변이를 잇는 경로 전용. 기존 호출부는 그대로 둔다. */
export async function closeObservationWorkOrderWithToken(
  workOrderId: string,
  expectedOperationsRevision: number,
  note: string | null,
  idempotencyKey: string,
  token: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetchWithToken<ObservationWorkOrderOperationsView>(`${operationsPath(workOrderId)}/close`, token, {
    method: "POST",
    body: { expectedOperationsRevision, note },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

/** 같은 요청의 세션 토큰 하나로 연속성 검사와 변이를 잇는 경로 전용. 기존 호출부는 그대로 둔다. */
export async function reopenObservationWorkOrderWithToken(
  workOrderId: string,
  expectedOperationsRevision: number,
  idempotencyKey: string,
  token: string,
): Promise<ObservationWorkOrderOperationsView> {
  return coreFetchWithToken<ObservationWorkOrderOperationsView>(`${operationsPath(workOrderId)}/reopen`, token, {
    method: "POST",
    body: { expectedOperationsRevision },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function listReobservationDrafts(
  workOrderId: string,
): Promise<ReobservationDraftView[]> {
  const response = await coreFetch<{ drafts: ReobservationDraftView[] }>(
    `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/reobservation-drafts`,
  );
  return response.drafts;
}
