import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => {
  class MissingSessionError extends Error {
    constructor() {
      super("세션이 없습니다 — 다시 로그인하세요.");
      this.name = "MissingSessionError";
    }
  }
  return { session: vi.fn(), MissingSessionError };
});
vi.mock("@/lib/core-api/session", () => ({
  getSessionToken: mocked.session,
  MissingSessionError: mocked.MissingSessionError,
}));
vi.mock("@/lib/core-api/env", () => ({ coreApiBaseUrl: () => "https://core.test" }));

import { NextRequest } from "next/server";

import { GET as readSourceContext } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/mask-inputs/source-context/route";

const fixture = JSON.parse(
  readFileSync("test/masked-wire-fixture.json", "utf-8"),
) as Record<string, unknown>;

const digest = fixture.sourceCalculationIdentityDigest as string;
const params = { params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1" }) };
const corePath =
  `https://core.test/v3/sites/site-1/work-areas/area-1/mask-source-context?source_calculation_identity_digest=${encodeURIComponent(digest)}`;

function coreJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sourceRequest(query: string): NextRequest {
  return new NextRequest(`https://console.test/api/sites/site-1/work-areas/area-1/mask-inputs/source-context${query}`, {
    headers: { host: "console.test" },
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
  mocked.session.mockResolvedValue("token-operator-1");
});

describe("mask source-context BFF", () => {
  it("Core 고정 경로·snake 쿼리로 전달하고 닫힌 와이어를 그대로 둔다", async () => {
    const seen: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      seen.push(String(input));
      return coreJson(fixture.sourceContext);
    }));
    const response = await readSourceContext(sourceRequest(`?source_calculation_identity_digest=${encodeURIComponent(digest)}`), params);
    expect(response.status).toBe(200);
    expect(seen).toEqual([corePath]);
    expect(await response.json()).toEqual(fixture.sourceContext);
  });

  it("Core 404는 모르는 원본으로만 닫는다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ detail: "MASK_SOURCE_CONTEXT_NOT_FOUND" }, 404)));
    const response = await readSourceContext(sourceRequest(`?source_calculation_identity_digest=${encodeURIComponent(digest)}`), params);
    expect(response.status).toBe(404);
    const body = (await response.json()) as { code?: string };
    expect(body.code).toBe("MASK_SOURCE_CONTEXT_NOT_FOUND");
  });

  it("Core 409 사유를 수치 실패로 바꾸지 않고 싣는다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ detail: "SOURCE_NOT_ADMITTED" }, 409)));
    const response = await readSourceContext(sourceRequest(`?source_calculation_identity_digest=${encodeURIComponent(digest)}`), params);
    expect(response.status).toBe(409);
    const body = (await response.json()) as { code?: string };
    expect(body.code).toBe("SOURCE_NOT_ADMITTED");
  });

  it("형식이 어긋난 확인값은 Core에 닿기 전에 버린다", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const response = await readSourceContext(sourceRequest(`?source_calculation_identity_digest=not-a-digest`), params);
    expect(response.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("drift·범위 외 응답은 502로만 둔다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ ...(fixture.sourceContext as object), maxMaskBytes: "huge" })));
    const drifted = await readSourceContext(sourceRequest(`?source_calculation_identity_digest=${encodeURIComponent(digest)}`), params);
    expect(drifted.status).toBe(502);
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({
      ...(fixture.sourceContext as object),
      baselineSubject: { ...((fixture.sourceContext as { baselineSubject: object }).baselineSubject), siteId: "site-9" },
    })));
    const foreign = await readSourceContext(sourceRequest(`?source_calculation_identity_digest=${encodeURIComponent(digest)}`), params);
    expect(foreign.status).toBe(502);
  });
});
