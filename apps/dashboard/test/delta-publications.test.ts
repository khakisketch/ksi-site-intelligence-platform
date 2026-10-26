import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn() }));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/env", () => ({ coreApiBaseUrl: () => "https://core.test" }));

import { CoreApiError } from "@/lib/core-api/client";
import {
  classifyDeltaAvailability,
  DeltaPublicationRequestError,
  DeltaUpstreamTimeoutError,
  getDeltaPublication,
  isDeltaLifetimeSeconds,
  isDigest,
  isOpaquePublicationId,
  parseDeltaChunkRange,
  parseDeltaPublicationBytes,
  parseDeltaPublicationDetail,
  parseDeltaPublicationIntent,
  parseDeltaPublicationRequest,
  readDeltaPublicationBytes,
  requestDeltaPublication,
} from "@/lib/core-api/delta-publications";

const digest = (marker: string) => `sha256:${marker.repeat(64).slice(0, 64)}`;
const source = {
  sourceCalculationIdentityDigest: digest("a"),
  sourceNumericResultIdentityDigest: digest("b"),
  sourceCoverageWitnessDigest: digest("c"),
};
const scope = { siteId: "site-1", workAreaId: "area-1", publicationId: "delta-pub-1", source };

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const GRID_TRANSFORM: [number, number, number, number, number, number] = [1, 0, 100, 0, -1, 200];
const GRID_BOUNDS: [number, number, number, number] = [100, 196, 104, 200];
const V3_CONTRACT = "external-masked-volume-calculation-identity.v3";

function intentShape() {
  return {
    publicationId: "delta-pub-1",
    organizationId: "org-1",
    siteId: "site-1",
    workAreaId: "area-1",
    sourceContractVersion: V3_CONTRACT,
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

function detailShape() {
  return {
    publicationId: "delta-pub-1",
    organizationId: "org-1",
    siteId: "site-1",
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
      siteId: "site-1",
      workAreaId: "area-1",
      sourceContractVersion: V3_CONTRACT,
      ...source,
      deltaSign: "CURRENT_MINUS_BASELINE",
      gridRows: 4,
      gridColumns: 4,
      transform: GRID_TRANSFORM,
      transformDigest: digest("e"),
      gridCrsIdentifier: "EPSG:5186",
      gridCrsDigest: digest("e"),
      bounds: GRID_BOUNDS,
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
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("test-token");
});

describe("delta publication request validation", () => {
  it("accepts exactly the three source digests plus identifier and lifetime", () => {
    expect(parseDeltaPublicationRequest({
      publicationId: "delta-pub-1",
      ...source,
      lifetimeSeconds: 3600,
    })).toEqual({ publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600 });
  });

  it("rejects caller-supplied grids, coordinates, sizes, and policies before Core", () => {
    for (const extra of [
      { gridRows: 4, gridColumns: 4 },
      { transform: [1, 0, 0, 0, -1, 0] },
      { outputSizeBytes: 10 },
      { policyDigest: digest("d") },
      { organizationId: "org-other" },
      { dtype: "FLOAT64" },
    ]) {
      expect(() => parseDeltaPublicationRequest({
        publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600, ...extra,
      })).toThrow(DeltaPublicationRequestError);
    }
  });

  it("rejects malformed digests, identifiers, and lifetimes", () => {
    expect(() => parseDeltaPublicationRequest({
      publicationId: "delta-pub-1", ...source, sourceCoverageWitnessDigest: "coverage-witness", lifetimeSeconds: 3600,
    })).toThrow(DeltaPublicationRequestError);
    expect(() => parseDeltaPublicationRequest({
      publicationId: "../escape", ...source, lifetimeSeconds: 3600,
    })).toThrow(DeltaPublicationRequestError);
    expect(() => parseDeltaPublicationRequest({
      publicationId: "https://evil.test/x", ...source, lifetimeSeconds: 3600,
    })).toThrow(DeltaPublicationRequestError);
    expect(() => parseDeltaPublicationRequest({
      publicationId: "delta-pub-1", ...source, lifetimeSeconds: 0,
    })).toThrow(DeltaPublicationRequestError);
    expect(() => parseDeltaPublicationRequest({
      publicationId: "delta-pub-1", ...source, lifetimeSeconds: 1.5,
    })).toThrow(DeltaPublicationRequestError);
  });

  it("never mistakes a path, URL, or capability for an opaque identifier", () => {
    expect(isOpaquePublicationId("delta-pub-1")).toBe(true);
    for (const bad of ["../x", "/abs", "a/b", "s3:bucket", "http://x", "https://x", "cap:read", "a\nb", "x".repeat(129), ""]) {
      expect(isOpaquePublicationId(bad)).toBe(false);
    }
    expect(isDigest(digest("a"))).toBe(true);
    expect(isDigest("sha256:ZZZ")).toBe(false);
    expect(isDigest(`SHA256:${"a".repeat(64)}`)).toBe(false);
    expect(isDeltaLifetimeSeconds(3600)).toBe(true);
    expect(isDeltaLifetimeSeconds(0)).toBe(false);
  });
});

describe("delta publication chunk ranges", () => {
  it("accepts bounded ranges and rejects everything above the 1MiB cap", () => {
    expect(parseDeltaChunkRange(0, 1024)).toEqual({ offset: 0, length: 1024 });
    expect(parseDeltaChunkRange(0, 1024 * 1024)).toEqual({ offset: 0, length: 1024 * 1024 });
    for (const [offset, length] of [[-1, 10], [0, 0], [0, 1024 * 1024 + 1], [1.5, 10], [0, Number.NaN], ["0", 10]] as const) {
      expect(() => parseDeltaChunkRange(offset as never, length as never)).toThrow(DeltaPublicationRequestError);
    }
  });
});

describe("delta publication closed response validation", () => {
  it("rejects scope mismatch instead of attributing foreign bytes to this scope", () => {
    // 의도: 요청 범위와 다른 구역이면 범위 오류로 버린다.
    expect(() => parseDeltaPublicationIntent(
      { ...intentShape(), workAreaId: "area-2" }, scope,
    )).toThrow("요청 범위");
    // 상세: 최상위와 서술자가 서로 모순되면 형식이 닫히지 않은 것으로 버린다.
    expect(() => parseDeltaPublicationDetail(
      { ...detailShape(), siteId: "site-2" }, scope,
    )).toThrow("응답 형식");
    expect(() => parseDeltaPublicationDetail({
      ...detailShape(),
      descriptor: { ...(detailShape().descriptor as Record<string, unknown>), workAreaId: "area-9" },
    }, scope)).toThrow("응답 형식");
  });

  it("rejects a descriptor that echoes different source digests instead of fabricating coverage", () => {
    const otherCoverage = `sha256:${"9".repeat(64)}`;
    expect(isDigest(otherCoverage)).toBe(true);
    expect(() => parseDeltaPublicationDetail({
      ...detailShape(),
      descriptor: { ...(detailShape().descriptor as Record<string, unknown>), sourceCoverageWitnessDigest: otherCoverage },
    }, scope)).toThrow("요청 범위");
  });

  it("rejects malformed shapes instead of rendering partial facts", () => {
    expect(() => parseDeltaPublicationIntent({ ...intentShape(), status: 42 }, scope)).toThrow("응답 형식");
    expect(() => parseDeltaPublicationDetail({ ...detailShape(), descriptor: null }, scope)).toThrow("응답 형식");
  });

  it("validates byte slice echo, offset, and strict base64 without decoding grids", () => {
    const chunk = Buffer.from("abcdefgh").toString("base64");
    expect(parseDeltaPublicationBytes(
      { publicationId: "delta-pub-1", offset: 0, contentBase64: chunk },
      { publicationId: "delta-pub-1", offset: 0, length: 8 },
    )).toEqual({ publicationId: "delta-pub-1", offset: 0, contentBase64: chunk });
    expect(() => parseDeltaPublicationBytes(
      { publicationId: "delta-pub-1", offset: 8, contentBase64: chunk },
      { publicationId: "delta-pub-1", offset: 0, length: 8 },
    )).toThrow("응답 형식");
    expect(() => parseDeltaPublicationBytes(
      { publicationId: "delta-pub-1", offset: 0, contentBase64: "not base64!!" },
      { publicationId: "delta-pub-1", offset: 0, length: 8 },
    )).toThrow("응답 형식");
    expect(() => parseDeltaPublicationBytes(
      { publicationId: "delta-pub-1", offset: 0, contentBase64: "abc" },
      { publicationId: "delta-pub-1", offset: 0, length: 8 },
    )).toThrow("응답 형식");
  });

  it("rejects unknown response fields instead of cherry-picking known ones", () => {
    expect(() => parseDeltaPublicationIntent({ ...intentShape(), unexpected: "value" }, scope))
      .toThrow("응답 형식");
    expect(() => parseDeltaPublicationDetail(
      { ...detailShape(), descriptor: { ...detailShape().descriptor, unexpected: 1 } }, scope,
    )).toThrow("응답 형식");
    expect(() => parseDeltaPublicationBytes(
      { publicationId: "delta-pub-1", offset: 0, contentBase64: Buffer.from("abcdefgh").toString("base64"), extra: true },
      { publicationId: "delta-pub-1", offset: 0, length: 8 },
    )).toThrow("응답 형식");
  });

  it("restricts status, contract, dtype, sign, and unit literals to the Core contract", () => {
    expect(() => parseDeltaPublicationIntent({ ...intentShape(), status: "READY" }, scope))
      .toThrow("응답 형식");
    expect(() => parseDeltaPublicationIntent({ ...intentShape(), sourceContractVersion: "v9" }, scope))
      .toThrow("응답 형식");
    const descriptor = detailShape().descriptor;
    for (const patch of [
      { dtype: "FLOAT32" },
      { deltaSign: "BASELINE_MINUS_CURRENT" },
      { verticalUnit: "meter" },
      { sourceContractVersion: "external-relative-volume-calculation-report.v9" },
      { contractVersion: "external-masked-volume-delta-publication.v9" },
    ]) {
      expect(() => parseDeltaPublicationDetail(
        { ...detailShape(), descriptor: { ...descriptor, ...patch } }, scope,
      )).toThrow("응답 형식");
    }
  });

  it("binds top-level policy, time, output, and scope to the descriptor instead of trusting either alone", () => {
    const descriptor = detailShape().descriptor;
    expect(() => parseDeltaPublicationDetail({
      ...detailShape(),
      policyDigest: digest("9"),
    }, scope)).toThrow("응답 형식");
    expect(() => parseDeltaPublicationDetail({
      ...detailShape(),
      descriptor: { ...descriptor, outputId: "delta-out-other" },
    }, scope)).toThrow("응답 형식");
    expect(() => parseDeltaPublicationDetail({
      ...detailShape(),
      descriptor: { ...descriptor, organizationId: "org-other" },
    }, scope)).toThrow("응답 형식");
    expect(() => parseDeltaPublicationDetail({
      ...detailShape(),
      descriptor: { ...descriptor, expiresAt: "2026-10-26T02:00:00Z" },
    }, scope)).toThrow("응답 형식");
    expect(() => parseDeltaPublicationDetail({
      ...detailShape(),
      descriptor: { ...descriptor, issuedAt: "2026-10-26T00:00:00Z", expiresAt: "2026-10-26T00:00:00Z" },
    }, scope)).toThrow("응답 형식");
  });

  it("rejects non-finite, rotated, or bounds-mismatched grids without doing raster math", () => {
    const descriptor = detailShape().descriptor;
    for (const patch of [
      { transform: [1, 1, 100, 0, -1, 200] },
      { transform: [1, 0, 100, 0, 1, 200] },
      { transform: [1, 0, 100, 0, -1, Number.POSITIVE_INFINITY] },
      { transform: [1, 0, 100, 0, -1, 200, 0] },
      { bounds: [100, 196, 104, 201] },
      { bounds: [104, 196, 100, 200] },
      { gridRows: 5 },
    ]) {
      expect(() => parseDeltaPublicationDetail(
        { ...detailShape(), descriptor: { ...descriptor, ...patch } }, scope,
      )).toThrow("응답 형식");
    }
    // UTC가 아닌 시각·역전된 구간도 거부한다.
    expect(() => parseDeltaPublicationDetail({
      ...detailShape(), issuedAt: "2026-10-26 00:00:00",
    }, scope)).toThrow("응답 형식");
  });

  it("rejects non-canonical base64 padding bits and oversized decoded payloads", () => {
    // "AB=="는 패딩 양자의 미사용 비트가 0이 아니라 정식이 아니다.
    expect(() => parseDeltaPublicationBytes(
      { publicationId: "delta-pub-1", offset: 0, contentBase64: "AB==" },
      { publicationId: "delta-pub-1", offset: 0, length: 8 },
    )).toThrow("응답 형식");
    // 복원 바이트(8)가 요청 길이(4)를 넘으면 잘라 쓰지 않는다.
    const chunk = Buffer.from("abcdefgh").toString("base64");
    expect(() => parseDeltaPublicationBytes(
      { publicationId: "delta-pub-1", offset: 0, contentBase64: chunk },
      { publicationId: "delta-pub-1", offset: 0, length: 4 },
    )).toThrow("응답 형식");
    // 정식 빈 조각도 거부한다.
    expect(() => parseDeltaPublicationBytes(
      { publicationId: "delta-pub-1", offset: 0, contentBase64: "" },
      { publicationId: "delta-pub-1", offset: 0, length: 8 },
    )).toThrow("응답 형식");
  });
});

describe("delta availability classification", () => {
  it("lets expiry win even for a cached PUBLISHED view and never reads numeric status", () => {
    expect(classifyDeltaAvailability({ detailStatus: "PUBLISHED", hasDescriptor: true, expiresAtMs: 100, nowMs: 200 }))
      .toBe("EXPIRED");
    expect(classifyDeltaAvailability({ detailStatus: "PUBLISHED", hasDescriptor: true, expiresAtMs: 300, nowMs: 200 }))
      .toBe("AVAILABLE");
    expect(classifyDeltaAvailability({ detailStatus: "FAILED", hasDescriptor: false, expiresAtMs: 9_999_999_999_999, nowMs: 0 }))
      .toBe("UNAVAILABLE");
    expect(classifyDeltaAvailability({ detailStatus: "REVOKED", hasDescriptor: false, expiresAtMs: 9_999_999_999_999, nowMs: 0 }))
      .toBe("UNAVAILABLE");
    expect(classifyDeltaAvailability({ detailStatus: null, hasDescriptor: false, expiresAtMs: 1000, nowMs: 999 }))
      .toBe("PENDING");
    expect(classifyDeltaAvailability({ detailStatus: null, hasDescriptor: false, expiresAtMs: 1000, nowMs: 1000 }))
      .toBe("EXPIRED");
    expect(classifyDeltaAvailability({ detailStatus: null, hasDescriptor: false, expiresAtMs: null, nowMs: 0 }))
      .toBe("PENDING");
  });
});

describe("delta Core transport", () => {
  function stubFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push({ url, init });
      return handler(url, init);
    }));
    return calls;
  }

  it("posts only source digests with the opaque key and never touches numeric endpoints", async () => {
    const calls = stubFetch(() => jsonResponse(intentShape(), 202));
    const intent = await requestDeltaPublication("site-1", "area-1", {
      publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600,
    });
    expect(intent.publicationId).toBe("delta-pub-1");
    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe("https://core.test/v1/sites/site-1/work-areas/area-1/delta-publications");
    expect(calls[0]!.init?.method).toBe("POST");
    expect(calls[0]!.init?.headers).toMatchObject({ Authorization: "Bearer test-token" });
    expect(calls[0]!.init?.headers).not.toHaveProperty("Idempotency-Key");
    const sent = JSON.parse(String(calls[0]!.init?.body));
    expect(sent).toEqual({ publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600 });
    expect(calls[0]!.url).not.toContain("analyses");
  });

  it("reuses the same publication key byte-for-byte on ambiguous retry", async () => {
    const calls = stubFetch(() => jsonResponse(intentShape(), 202));
    const input = { publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600 };
    await requestDeltaPublication("site-1", "area-1", input);
    await requestDeltaPublication("site-1", "area-1", input);
    expect(calls).toHaveLength(2);
    expect(calls[0]!.init?.body).toBe(calls[1]!.init?.body);
  });

  it("passes Core verdicts through untouched and maps aborts to timeouts", async () => {
    stubFetch(() => jsonResponse({ verdict: "DELTA_SCOPE_DENIED" }, 403));
    await expect(requestDeltaPublication("site-1", "area-1", {
      publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600,
    })).rejects.toMatchObject({ status: 403 } satisfies Partial<CoreApiError>);

    stubFetch(() => jsonResponse({ verdict: "DELTA_PUBLICATION_NOT_FOUND" }, 404));
    await expect(getDeltaPublication("site-1", "area-1", "delta-pub-1", source))
      .rejects.toMatchObject({ status: 404 } satisfies Partial<CoreApiError>);

    const controller = new AbortController();
    controller.abort();
    stubFetch((_url, init) => {
      if (init?.signal?.aborted === true) {
        throw new DOMException("This operation was aborted", "AbortError");
      }
      return jsonResponse(intentShape(), 202);
    });
    await expect(requestDeltaPublication("site-1", "area-1", {
      publicationId: "delta-pub-1", ...source, lifetimeSeconds: 3600,
    }, { signal: controller.signal })).rejects.toBeInstanceOf(DeltaUpstreamTimeoutError);
  });

  it("reads byte slices with strict 1MiB query bounds and echo validation", async () => {
    const chunk = Buffer.from("abcdefgh").toString("base64");
    const calls = stubFetch(() => jsonResponse({ publicationId: "delta-pub-1", offset: 0, contentBase64: chunk }));
    const bytes = await readDeltaPublicationBytes("site-1", "area-1", "delta-pub-1", { offset: 0, length: 8 });
    expect(bytes.contentBase64).toBe(chunk);
    expect(calls[0]!.url).toContain("/bytes?offset=0&length=8");
  });
});
