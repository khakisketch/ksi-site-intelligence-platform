import "server-only";

import { coreFetch } from "./client";
import type {
  EventDetailResponse,
  EventSeverity,
  EventStatus,
  EventSummaryResponse,
  EventTransitionInput,
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
