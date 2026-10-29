import { NextResponse, type NextRequest } from "next/server";
import { getSessionToken } from "@/lib/core-api/session";
import { coreFetchWithToken } from "@/lib/core-api/client";
import { continuityFingerprint } from "@/lib/core-api/work-order-continuity";
import type { WhoAmIResponse } from "@/lib/core-api/types";
import { parseShellSites } from "@/components/nav/shell-site-validation";

/** Read-only, same-token Core authorization. The claim is a continuity guard, not a credential. */
export async function GET(request: NextRequest) {
  const expected = request.headers.get("x-ksi-continuity-fingerprint");
  const reply = (body: unknown, status: number) => NextResponse.json(body, { status, headers: { "Cache-Control": "private, no-store" } });
  if (!expected || !/^v1-[0-9a-f]{64}$/.test(expected)) return reply({}, 400);
  try {
    const token = await getSessionToken();
    const principal = await coreFetchWithToken<WhoAmIResponse>("/v1/auth/whoami", token);
    const fingerprint = continuityFingerprint(principal);
    if (!fingerprint || fingerprint !== expected) return reply({}, 409);
    const result = await coreFetchWithToken<{ sites: unknown }>("/v1/sites", token);
    const sites = parseShellSites(result?.sites);
    if (!sites) return reply({}, 502);
    return reply({ fingerprint, sites }, 200);
  } catch {
    return reply({}, 503);
  }
}
