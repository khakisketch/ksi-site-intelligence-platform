import "server-only";

import { coreFetch } from "./client";
import type { CopilotAnswerView } from "./types";

export async function askCopilot(input: {
  siteId: string;
  workOrderId: string;
  question: string;
}): Promise<CopilotAnswerView> {
  return coreFetch<CopilotAnswerView>("/v1/copilot/query", {
    method: "POST",
    body: input,
  });
}
