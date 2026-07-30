import "server-only";

import { coreFetch } from "./client";
import type { WhoAmIResponse } from "./types";

export async function whoAmI(): Promise<WhoAmIResponse> {
  return coreFetch<WhoAmIResponse>("/v1/auth/whoami");
}
