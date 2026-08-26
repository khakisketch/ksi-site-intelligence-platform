import "server-only";

import { coreFetch } from "./client";
import type {
  ConversationDetailView,
  ConversationListResponse,
  CopilotConversation,
  CopilotExchangeResponse,
} from "./types";

export async function listSiteConversations(
  siteId: string,
): Promise<ConversationListResponse> {
  return coreFetch<ConversationListResponse>(
    `/v1/sites/${encodeURIComponent(siteId)}/copilot/conversations`,
  );
}

export async function createSiteConversation(
  siteId: string,
  workOrderId?: string,
): Promise<CopilotConversation> {
  return coreFetch<CopilotConversation>(
    `/v1/sites/${encodeURIComponent(siteId)}/copilot/conversations`,
    { method: "POST", body: { workOrderId: workOrderId ?? null } },
  );
}

export async function getConversation(
  conversationId: string,
): Promise<ConversationDetailView> {
  return coreFetch<ConversationDetailView>(
    `/v1/copilot/conversations/${encodeURIComponent(conversationId)}`,
  );
}

export async function sendConversationMessage(
  conversationId: string,
  input: { clientMessageId: string; question: string },
): Promise<CopilotExchangeResponse> {
  return coreFetch<CopilotExchangeResponse>(
    `/v1/copilot/conversations/${encodeURIComponent(conversationId)}/messages`,
    { method: "POST", body: input },
  );
}
