import "server-only";

import { coreFetch, coreFetchWithToken } from "./client";

export type WorkRosterRoleHint = "ADMIN" | "FIELD_OPERATOR" | "VIEWER";
export type WorkRosterStatus = "ACTIVE" | "INACTIVE";

/** Roster data is organizational metadata. Core remains the only authority for account access. */
export interface OrganizationWorkRosterMember {
  schemaVersion: "1.0";
  organizationId: string;
  principalId: string;
  displayName: string;
  roleHint: WorkRosterRoleHint;
  status: WorkRosterStatus;
  revision: number;
  updatedAt: string;
  updatedBy: string;
}

export interface OrganizationWorkRosterResponse {
  members: OrganizationWorkRosterMember[];
}

export interface UpdateOrganizationWorkRosterMemberInput {
  expectedRevision: number;
  displayName: string;
  roleHint: WorkRosterRoleHint;
  status: WorkRosterStatus;
}

export interface WorkInboxItem {
  notificationRef: string;
  kind: "WORK_ORDER_ASSIGNED" | "EXTERNAL_REPORT_SHARED";
  target:
    | { kind: "WORK_ORDER"; workOrderId: string }
    | { kind: "EXTERNAL_REPORT"; siteId: string; reportRef: string };
  senderPrincipalId: string;
  createdAt: string;
  unread: boolean;
}

export interface WorkInboxResponse {
  items: WorkInboxItem[];
  nextCursor: string | null;
}

export async function listOrganizationWorkRoster({
  includeInactive = false,
  search = "",
}: { includeInactive?: boolean; search?: string } = {}): Promise<OrganizationWorkRosterResponse> {
  return coreFetch<OrganizationWorkRosterResponse>("/v1/organization-work-roster", {
    query: { includeInactive: includeInactive ? "true" : "false", search, limit: 100 },
  });
}

export async function updateOrganizationWorkRosterMember(
  principalId: string,
  input: UpdateOrganizationWorkRosterMemberInput,
  idempotencyKey: string,
): Promise<OrganizationWorkRosterMember> {
  return coreFetch<OrganizationWorkRosterMember>(`/v1/organization-work-roster/${encodeURIComponent(principalId)}`, {
    method: "PUT",
    body: input,
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

/**
 * 같은 요청의 세션 토큰 하나로 Core whoami 연속성 검사와 변이를 잇는 경로 전용 —
 * 토큰을 두 번 읽으면 검사와 변이 사이 세션 교체(TOCTOU)가 생긴다. 기존 호출부는 그대로 둔다.
 */
export async function updateOrganizationWorkRosterMemberWithToken(
  principalId: string,
  input: UpdateOrganizationWorkRosterMemberInput,
  idempotencyKey: string,
  token: string,
): Promise<OrganizationWorkRosterMember> {
  return coreFetchWithToken<OrganizationWorkRosterMember>(`/v1/organization-work-roster/${encodeURIComponent(principalId)}`, token, {
    method: "PUT",
    body: input,
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function listWorkInbox({
  unreadOnly = false,
  after,
}: { unreadOnly?: boolean; after?: string } = {}): Promise<WorkInboxResponse> {
  return coreFetch<WorkInboxResponse>("/v1/work-inbox", {
    query: { unreadOnly: unreadOnly ? "true" : "false", after, limit: 20 },
  });
}

export async function markWorkInboxItemRead(notificationRef: string, idempotencyKey: string): Promise<{
  schemaVersion: "1.0";
  organizationId: string;
  recipientPrincipalId: string;
  notificationRef: string;
  readAt: string;
}> {
  return coreFetch(`/v1/work-inbox/${encodeURIComponent(notificationRef)}/read`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function createExternalRelativeVolumeReportShare(
  reportRef: string,
  recipientPrincipalId: string,
  idempotencyKey: string,
): Promise<{
  schemaVersion: "1.0";
  shareRef: string;
  organizationId: string;
  senderPrincipalId: string;
  recipientPrincipalId: string;
  siteId: string;
  reportRef: string;
  reportDigest: string;
  createdAt: string;
}> {
  return coreFetch(`/v1/external-relative-volume-reports/${encodeURIComponent(reportRef)}/shares`, {
    method: "POST",
    body: { recipientPrincipalId },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function shareExternalSingleVolumeReport(
  reportRef: string,
  recipientPrincipalId: string,
  idempotencyKey: string,
): Promise<{
  schemaVersion: "1.0";
  shareRef: string;
  organizationId: string;
  senderPrincipalId: string;
  recipientPrincipalId: string;
  siteId: string;
  reportRef: string;
  reportDigest: string;
  createdAt: string;
}> {
  return coreFetch(`/v1/external-single-volume-reports/${encodeURIComponent(reportRef)}/shares`, {
    method: "POST",
    body: { recipientPrincipalId },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}
