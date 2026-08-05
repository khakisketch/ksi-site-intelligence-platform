import "server-only";

import { coreFetch } from "./client";
import type {
  EventDetailResponse,
  EventSeverity,
  EventStatus,
  EventSummaryResponse,
  EventTransitionInput,
  EvidenceUploadResponse,
  EvidenceViewResponse,
  TransitionResponse,
  TriageStatus,
} from "./types";

export interface ListEventsFilter {
  siteId?: string;
  missionId?: string;
  edgeDeviceId?: string;
  status?: EventStatus;
  severity?: EventSeverity;
  triage?: TriageStatus;
  limit?: number;
  offset?: number;
}

export async function listEvents(
  filter: ListEventsFilter = {},
): Promise<{ events: EventSummaryResponse[]; count: number }> {
  return coreFetch<{ events: EventSummaryResponse[]; count: number }>("/v1/events", {
    query: { ...filter },
  });
}

export async function getEvent(eventKey: string): Promise<EventDetailResponse> {
  return coreFetch<EventDetailResponse>(`/v1/events/${encodeURIComponent(eventKey)}`);
}

export async function transitionEvent(
  eventKey: string,
  input: EventTransitionInput,
): Promise<TransitionResponse> {
  return coreFetch<TransitionResponse>(`/v1/events/${encodeURIComponent(eventKey)}/transitions`, {
    method: "POST",
    body: input,
  });
}

/**
 * 증거 업로드 등록 — presigned PUT URL 을 받는다(ADR-KSI-010 §1).
 *
 * Core 는 바이트를 중계하지 않는다. 이 응답의 URL 로 **브라우저가 스토리지에
 * 직접** PUT 한다 — 대시보드 서버도 파일을 거치지 않는다.
 */
export async function registerEvidence(
  eventKey: string,
  input: { artifactId: string; contentType: string },
): Promise<EvidenceUploadResponse> {
  return coreFetch<EvidenceUploadResponse>(
    `/v1/events/${encodeURIComponent(eventKey)}/evidence`,
    { method: "POST", body: input },
  );
}

/** 증거 열람 URL — 수명이 짧다(분 단위). 폐기된 증거는 410 이다. */
export async function getEvidenceViewUrl(
  eventKey: string,
  artifactId: string,
): Promise<EvidenceViewResponse> {
  return coreFetch<EvidenceViewResponse>(
    `/v1/events/${encodeURIComponent(eventKey)}/evidence/${encodeURIComponent(artifactId)}`,
  );
}
