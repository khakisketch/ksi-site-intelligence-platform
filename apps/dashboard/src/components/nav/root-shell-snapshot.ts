import "server-only";
import { getSessionToken } from "@/lib/core-api/session";
import { coreFetchWithToken } from "@/lib/core-api/client";
import { continuityFingerprint } from "@/lib/core-api/work-order-continuity";
import type { SiteView, WhoAmIResponse } from "@/lib/core-api/types";

/** All personal shell data and its fingerprint share exactly one bearer token. */
export async function readRootShellSnapshot() {
  try {
    const token = await getSessionToken();
    const principal = await coreFetchWithToken<WhoAmIResponse>("/v1/auth/whoami", token);
    const fingerprint = continuityFingerprint(principal);
    if (!fingerprint) return null;
    const sites = await coreFetchWithToken<{ sites: SiteView[] }>("/v1/sites", token)
      .then((result) => result.sites).catch(() => null);
    return { principal, fingerprint, sites };
  } catch { return null; }
}
