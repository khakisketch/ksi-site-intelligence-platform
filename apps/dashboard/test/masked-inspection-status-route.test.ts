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

import { GET as readInspectionStatus } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/mask-inputs/[maskChildId]/inspection-status/route";

const fixture = JSON.parse(
  readFileSync("test/masked-wire-fixture.json", "utf-8"),
) as Record<string, unknown>;

const params = { params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1", maskChildId: "mask-child-1" }) };
const corePath =
  "https://core.test/v3/sites/site-1/work-areas/area-1/mask-children/mask-child-1/inspection-status";

function coreJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sourceRequest(): NextRequest {
  return new NextRequest(
    "https://console.test/api/sites/site-1/work-areas/area-1/mask-inputs/mask-child-1/inspection-status",
    { headers: { host: "console.test" } },
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  mocked.session.mockResolvedValue("token-operator-1");
});

describe("mask inspection-status BFF", () => {
  it("Core 고정 경로로 전달하고 닫힌 와이어를 그대로 둔다", async () => {
    const seen: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      seen.push(String(input));
      return coreJson({ ...(fixture.inspectionCompleted as object), maskChildId: "mask-child-1" });
    }));
    const response = await readInspectionStatus(sourceRequest(), params);
    expect(response.status).toBe(200);
    expect(seen).toEqual([corePath]);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body.status).toBe("COMPLETED");
    expect(body.reasonCode).toBeNull();
  });

  it("terminal 실패를 그대로 싣는다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ ...(fixture.inspectionRejected as object), maskChildId: "mask-child-1" })));
    const response = await readInspectionStatus(sourceRequest(), params);
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body.status).toBe("REJECTED");
    expect(body.reasonCode).toBe("MASK_NODATA_REJECTED");
  });

  it("drift·범위 외 응답은 502로만 둔다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({
      ...(fixture.inspectionCompleted as object),
      maskChildId: "mask-child-1",
      reasonCode: "MASK_NODATA_REJECTED",
    })));
    expect((await readInspectionStatus(sourceRequest(), params)).status).toBe(502);
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({
      ...(fixture.inspectionCompleted as object),
      maskChildId: "mask-child-1",
      status: "COMPLETED",
      manifestDigest: null,
    })));
    expect((await readInspectionStatus(sourceRequest(), params)).status).toBe(502);
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({
      ...(fixture.inspectionCompleted as object),
      maskChildId: "mask-child-1",
      siteId: "site-9",
    })));
    expect((await readInspectionStatus(sourceRequest(), params)).status).toBe(502);
  });

  it("Core 404·403을 그대로 닫는다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ detail: "MASK_CHILD_NOT_FOUND" }, 404)));
    const notFound = await readInspectionStatus(sourceRequest(), params);
    expect(notFound.status).toBe(404);
    expect(((await notFound.json()) as { code?: string }).code).toBe("MASK_CHILD_NOT_FOUND");
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ detail: "MASK_SCOPE_DENIED" }, 403)));
    const denied = await readInspectionStatus(sourceRequest(), params);
    expect(denied.status).toBe(403);
    expect(((await denied.json()) as { code?: string }).code).toBe("MASK_SCOPE_DENIED");
  });

  it("형식이 어긋난 자식 id는 Core에 닿기 전에 버린다", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const bad = { params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1", maskChildId: "../escape" }) };
    const response = await readInspectionStatus(sourceRequest(), bad);
    expect(response.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
