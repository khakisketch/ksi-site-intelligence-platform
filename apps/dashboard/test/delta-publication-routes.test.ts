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

import { POST as createPublication } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/delta-publications/route";
import { GET as readPublication } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/delta-publications/[publicationId]/route";
import { GET as readBytes } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/delta-publications/[publicationId]/bytes/route";

const digest = (marker: string) => `sha256:${marker.repeat(64).slice(0, 64)}`;
const source = {
  sourceCalculationIdentityDigest: digest("a"),
  sourceNumericResultIdentityDigest: digest("b"),
  sourceCoverageWitnessDigest: digest("c"),
};
const params = { params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1" }) };
const detailParams = {
  params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1", publicationId: "delta-pub-1" }),
};

function coreJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function request(url: string, init?: RequestInit): Request {
  return new Request(url, { headers: { host: "console.test" }, ...init });
}

function intentShape() {
  return {
    publicationId: "delta-pub-1",
    organizationId: "org-1",
    siteId: "site-1",
    workAreaId: "area-1",
    sourceContractVersion: "external-masked-volume-calculation-identity.v3",
    outputId: "delta-out-delta-pub-1",
    uploadFenceId: "upload-fence-delta-pub-1",
    ...source,
    gridRows: 4,
    gridColumns: 4,
    issuedAt: "2026-10-26T00:00:00Z",
    expiresAt: "2026-10-26T01:00:00Z",
    policyDigest: digest("d"),
    status: "PENDING",
    leaseGeneration: 0,
    leaseHolderPrincipalId: null,
    leaseHolderInstanceId: null,
    leaseIssuedAt: null,
    leaseExpiresAt: null,
  };
}

const detailQuery = `sourceCalculationIdentityDigest=${encodeURIComponent(source.sourceCalculationIdentityDigest)}&sourceNumericResultIdentityDigest=${encodeURIComponent(source.sourceNumericResultIdentityDigest)}&sourceCoverageWitnessDigest=${encodeURIComponent(source.sourceCoverageWitnessDigest)}`;

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("session-token");
});

describe("delta publication creation BFF", () => {
  it("forwards only the three source digests with the opaque key and lifetime", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(typeof input === "string" ? input : input.toString());
      expect(init?.headers).toMatchObject({ Authorization: "Bearer session-token" });
      expect(JSON.parse(String(init?.body))).toEqual({ publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600 });
      return coreJson(intentShape(), 202);
    }));
    const response = await createPublication(
      request("http://console.test/api", {
        method: "POST",
        headers: { "content-type": "application/json", host: "console.test" },
        body: JSON.stringify({ publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600 }),
      }) as never,
      params,
    );
    expect(response.status).toBe(202);
    expect((await response.json() as { publicationId: string }).publicationId).toBe("delta-pub-1");
    expect(calls[0]).toBe("https://core.test/v1/sites/site-1/work-areas/area-1/delta-publications");
    vi.unstubAllGlobals();
  });

  it("rejects grids, callers, URLs, and lifetimes before Core without leaking tokens", async () => {
    const fetchMock = vi.fn(async () => coreJson(intentShape(), 202));
    vi.stubGlobal("fetch", fetchMock);
    const badBodies = [
      { publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600, gridRows: 4 },
      { publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600, organizationId: "org-x" },
      { publicationId: "../escape", ...source, lifetimeSeconds: 3600 },
      { publicationId: "https://evil.test/x", ...source, lifetimeSeconds: 3600 },
      { publicationId: "delta-pub-1", ...source, lifetimeSeconds: 0 },
      { publicationId: "delta-pub-1", sourceCalculationIdentityDigest: "nope", sourceNumericResultIdentityDigest: source.sourceNumericResultIdentityDigest, sourceCoverageWitnessDigest: source.sourceCoverageWitnessDigest, lifetimeSeconds: 3600 },
    ];
    for (const body of badBodies) {
      const response = await createPublication(
        request("http://console.test/api", {
          method: "POST",
          headers: { "content-type": "application/json", host: "console.test" },
          body: JSON.stringify(body),
        }) as never,
        params,
      );
      expect(response.status).toBe(400);
    }
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("rejects cross-site mutation before session lookup and maps missing session to 401", async () => {
    const response = await createPublication(
      request("http://console.test/api", {
        method: "POST",
        headers: { "content-type": "application/json", host: "console.test", origin: "https://evil.test" },
        body: JSON.stringify({ publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600 }),
      }) as never,
      params,
    );
    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();

    mocked.session.mockRejectedValueOnce(new mocked.MissingSessionError());
    const denied = await createPublication(
      request("http://console.test/api", {
        method: "POST",
        headers: { "content-type": "application/json", host: "console.test" },
        body: JSON.stringify({ publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600 }),
      }) as never,
      params,
    );
    expect(denied.status).toBe(401);
  });

  it("passes Core 403/409 verdicts through without claiming numeric failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ verdict: "DELTA_SCOPE_DENIED" }, 403)));
    const forbidden = await createPublication(
      request("http://console.test/api", {
        method: "POST",
        headers: { "content-type": "application/json", host: "console.test" },
        body: JSON.stringify({ publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600 }),
      }) as never,
      params,
    );
    expect(forbidden.status).toBe(403);
    const forbiddenBody = (await forbidden.json()) as { code?: string; detail?: string };
    expect(forbiddenBody.code).toBe("DELTA_SCOPE_DENIED");
    expect(JSON.stringify(forbiddenBody)).not.toContain("수치");
    vi.unstubAllGlobals();
  });
});

describe("delta publication detail BFF", () => {
  it("requires the exact three source digests as opaque-free echo input", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({})));
    for (const url of [
      `http://console.test/api/x`,
      `http://console.test/api/x?sourceCalculationIdentityDigest=${encodeURIComponent(source.sourceCalculationIdentityDigest)}`,
    ]) {
      const response = await readPublication(request(url) as never, detailParams);
      expect(response.status).toBe(400);
    }
    vi.unstubAllGlobals();
  });

  it("rejects path-shaped identifiers and scope-mismatched echoes", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({})));
    const bad = await readPublication(request(`http://console.test/api/x?${detailQuery}`) as never, {
      params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1", publicationId: "..%2Fescape" }),
    });
    expect(bad.status).toBe(400);

    vi.stubGlobal("fetch", vi.fn(async () => coreJson({
      publicationId: "delta-pub-1",
      organizationId: "org-1",
      siteId: "site-OTHER",
      workAreaId: "area-1",
      outputId: "delta-out-delta-pub-1",
      issuedAt: "2026-10-26T00:00:00Z",
      expiresAt: "2026-10-26T01:00:00Z",
      policyDigest: digest("d"),
      status: "PUBLISHED",
      reason: null,
      descriptor: {
        contractVersion: "external-masked-volume-delta-publication.v1",
        publicationId: "delta-pub-1",
        organizationId: "org-1",
        siteId: "site-OTHER",
        workAreaId: "area-1",
        sourceContractVersion: "external-masked-volume-calculation-identity.v3",
        ...source,
        deltaSign: "CURRENT_MINUS_BASELINE",
        gridRows: 4,
        gridColumns: 4,
        transform: [1, 0, 100, 0, -1, 200],
        transformDigest: digest("e"),
        gridCrsIdentifier: "EPSG:5186",
        gridCrsDigest: digest("e"),
        bounds: [100, 196, 104, 200],
        verticalUnit: "metre",
        dtype: "FLOAT64",
        outputId: "delta-out-delta-pub-1",
        outputSha256: digest("f"),
        outputSizeBytes: 1024,
        issuedAt: "2026-10-26T00:00:00Z",
        expiresAt: "2026-10-26T01:00:00Z",
        publicationPolicyDigest: digest("d"),
        publicationDigest: null,
      },
    })));
    const mismatched = await readPublication(request(`http://console.test/api/x?${detailQuery}`) as never, detailParams);
    expect(mismatched.status).toBe(500);
    vi.unstubAllGlobals();
  });

  it("passes Core 404 through for pending versus terminal distinction", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ verdict: "DELTA_PUBLICATION_NOT_AVAILABLE" }, 404)));
    const response = await readPublication(request(`http://console.test/api/x?${detailQuery}`) as never, detailParams);
    expect(response.status).toBe(404);
    vi.unstubAllGlobals();
  });

  it("passes typed Core dispositions through with their codes intact", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ detail: "DELTA_PUBLICATION_FAILED" }, 404)));
    const failed = await readPublication(request(`http://console.test/api/x?${detailQuery}`) as never, detailParams);
    expect(failed.status).toBe(404);
    const failedBody = (await failed.json()) as { code?: string; detail?: string };
    expect(failedBody.code).toBe("DELTA_PUBLICATION_FAILED");

    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ detail: "DELTA_PUBLICATION_NOT_YET_PUBLISHED" }, 404)));
    const pending = await readPublication(request(`http://console.test/api/x?${detailQuery}`) as never, detailParams);
    expect(pending.status).toBe(404);
    expect(((await pending.json()) as { code?: string }).code).toBe("DELTA_PUBLICATION_NOT_YET_PUBLISHED");
    vi.unstubAllGlobals();
  });
});

describe("delta publication bytes BFF", () => {
  it("enforces offset/length shape and the 1MiB cap before Core", async () => {
    const fetchMock = vi.fn(async () => coreJson({}));
    vi.stubGlobal("fetch", fetchMock);
    const base = "http://console.test/api/x";
    for (const query of [
      "offset=-1&length=8",
      "offset=0&length=0",
      "offset=0&length=1048577",
      "offset=abc&length=8",
      "offset=0",
      "offset=0&length=8&length=8",
    ]) {
      const response = await readBytes(request(`${base}?${query}`) as never, detailParams);
      expect(response.status).toBe(400);
    }
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("forwards a bounded slice and validates the strict base64 echo", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toContain("offset=0&length=8");
      return coreJson({ publicationId: "delta-pub-1", offset: 0, contentBase64: Buffer.from("abcdefgh").toString("base64") });
    }));
    const response = await readBytes(request("http://console.test/api/x?offset=0&length=8") as never, detailParams);
    expect(response.status).toBe(200);
    expect((await response.json() as { offset: number }).offset).toBe(0);

    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ publicationId: "delta-pub-1", offset: 8, contentBase64: "AAAA" })));
    const tampered = await readBytes(request("http://console.test/api/x?offset=0&length=8") as never, detailParams);
    expect(tampered.status).toBe(500);
    vi.unstubAllGlobals();
  });

  it("rejects unknown echo fields, non-canonical padding bits, and oversized decoded payloads", async () => {
    const chunk = Buffer.from("abcdefgh").toString("base64");
    // 모르는 필드가 하나라도 있으면 외피가 닫히지 않은 것으로 버린다.
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({
      publicationId: "delta-pub-1", offset: 0, contentBase64: chunk, unexpected: true,
    })));
    expect((await readBytes(request("http://console.test/api/x?offset=0&length=8") as never, detailParams)).status).toBe(500);

    // "AB==" 패딩 비트가 정식이 아니다.
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ publicationId: "delta-pub-1", offset: 0, contentBase64: "AB==" })));
    expect((await readBytes(request("http://console.test/api/x?offset=0&length=8") as never, detailParams)).status).toBe(500);

    // 복원 8바이트가 요청 4바이트를 넘으면 잘라 쓰지 않는다.
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({ publicationId: "delta-pub-1", offset: 0, contentBase64: chunk })));
    expect((await readBytes(request("http://console.test/api/x?offset=0&length=4") as never, detailParams)).status).toBe(500);
    vi.unstubAllGlobals();
  });

  it("rejects a detail whose outer policy binding differs from the descriptor", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => coreJson({
      publicationId: "delta-pub-1",
      organizationId: "org-1",
      siteId: "site-1",
      workAreaId: "area-1",
      outputId: "delta-out-delta-pub-1",
      issuedAt: "2026-10-26T00:00:00Z",
      expiresAt: "2026-10-26T01:00:00Z",
      policyDigest: digest("9"),
      status: "PUBLISHED",
      reason: null,
      descriptor: {
        contractVersion: "external-masked-volume-delta-publication.v1",
        publicationId: "delta-pub-1",
        organizationId: "org-1",
        siteId: "site-1",
        workAreaId: "area-1",
        sourceContractVersion: "external-masked-volume-calculation-identity.v3",
        ...source,
        deltaSign: "CURRENT_MINUS_BASELINE",
        gridRows: 4,
        gridColumns: 4,
        transform: [1, 0, 100, 0, -1, 200],
        transformDigest: digest("e"),
        gridCrsIdentifier: "EPSG:5186",
        gridCrsDigest: digest("e"),
        bounds: [100, 196, 104, 200],
        verticalUnit: "metre",
        dtype: "FLOAT64",
        outputId: "delta-out-delta-pub-1",
        outputSha256: digest("f"),
        outputSizeBytes: 1024,
        issuedAt: "2026-10-26T00:00:00Z",
        expiresAt: "2026-10-26T01:00:00Z",
        publicationPolicyDigest: digest("d"),
        publicationDigest: null,
      },
    })));
    const response = await readPublication(request(`http://console.test/api/x?${detailQuery}`) as never, detailParams);
    expect(response.status).toBe(500);
    vi.unstubAllGlobals();
  });
});
