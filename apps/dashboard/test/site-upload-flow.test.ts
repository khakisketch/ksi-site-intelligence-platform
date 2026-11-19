import { describe, expect, it } from "vitest";

import { UploadFlowError, UploadSession, type UploadFlowDeps, type UploadFlowEvent, type UploadFlowInput } from "@/lib/site-upload-flow";

const hex = (value: string) => value.repeat(64);
const REF = `ers-v1-${hex("c")}`;
const DIGEST = `sha256:${hex("d")}`;
const SITE = "site-1";
const AREA = "wa-1";
const FP = `v1-${hex("e")}`;

function fileOf(name: string): File {
  return new File([new Uint8Array([1, 2, 3])], name);
}
const ortho = { kind: "ortho" as const, fileName: "ortho.tif", sha256: hex("a"), size: 3, declaredCrs: "EPSG:5186", producer: { name: "Pix4Dmatic", version: "1.67.0" }, file: fileOf("ortho.tif") };
const dsm = { kind: "dsm" as const, fileName: "dsm.tif", sha256: hex("b"), size: 3, declaredCrs: "EPSG:5186", producer: null, file: fileOf("dsm.tif") };

function input(files = [ortho, dsm]): UploadFlowInput {
  return { siteId: SITE, workAreaId: AREA, workAreaName: "북측 1차 구역", continuity: FP, files, startedLocal: "2026-11-18T09:20", endedLocal: "2026-11-18T10:05" };
}

type Call = { method: string; url: string; headers: Record<string, string>; body: unknown };

/** 요청을 기록하고, 등록·봉인 응답은 받은 신고서를 그대로 돌려주는 가짜 서버. 실패는 단계별로 주입한다. */
function fakeServer(now: () => number = () => Date.now()) {
  const calls: Call[] = [];
  const failures = new Map<string, Array<(() => Response | Promise<Response>) | "network">>();
  let declared: Record<string, unknown> | null = null;
  const view = (state: "REGISTERED" | "SEALED") => {
    const body = declared!;
    return {
      submissionRef: REF,
      state,
      submission: {
        submissionId: body.submissionId, revision: 1, observationEpochId: body.expectedEpochId, submittedAt: body.submittedAt,
        artifacts: body.artifacts,
        producerDeclaration: { producerKnowledge: body.producerKnowledge, softwareName: body.softwareName, softwareVersion: body.softwareVersion, sourceNote: body.sourceNote },
        inputDeclaration: {
          captureBasis: body.captureBasis, captureStartedAt: body.captureStartedAt, captureEndedAt: body.captureEndedAt, captureDate: body.captureDate,
          originalRetentionLocus: body.originalRetentionLocus, originalRetentionDetail: body.originalRetentionDetail, upstreamSource: body.upstreamSource, derivativeExport: body.derivativeExport,
        },
        submissionDigest: DIGEST,
      },
      manifest: state === "SEALED"
        ? {
            contractVersion: "external-reconstruction-manifest.v1", submissionId: body.submissionId, submissionRevision: 1, observationEpochId: body.expectedEpochId,
            submissionDigest: DIGEST, manifestDigest: DIGEST,
            entries: (body.artifacts as { artifactId: string; kind: string; declaredSha256: string; declaredSizeBytes: number }[]).map((item) => ({ artifactId: item.artifactId, kind: item.kind, observedSha256: item.declaredSha256, observedSizeBytes: item.declaredSizeBytes })),
          }
        : null,
    };
  };
  const json = (status: number, payload: unknown) => new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
  const handler = async (url: string, init: RequestInit = {}): Promise<Response> => {
    const method = init.method ?? "GET";
    const headers = (init.headers ?? {}) as Record<string, string>;
    const body = typeof init.body === "string" ? JSON.parse(init.body) : null;
    calls.push({ method, url, headers, body });
    const step = url.endsWith("/observation-work-orders") ? "create"
      : url.endsWith("/external-reconstruction-context") ? "context"
      : url.endsWith("-submissions-v3") ? "register"
      : url.endsWith("/upload-grants") ? "grants"
      : url.endsWith("/seal") ? "seal" : "unknown";
    const queued = failures.get(step)?.shift();
    if (queued === "network") throw new TypeError("network down");
    if (queued) return queued();
    if (step === "create") return json(201, { workOrderId: "wo-1", siteId: SITE, workAreaIds: [AREA] });
    if (step === "context") return json(200, { workOrderId: "wo-1", siteId: SITE, expectedEpochId: "epoch-1", executionMode: "EXTERNAL_RECONSTRUCTION" });
    if (step === "register") { declared = body as Record<string, unknown>; return json(201, view("REGISTERED")); }
    if (step === "grants") {
      const ids = (declared!.artifacts as { artifactId: string }[]).map((item) => item.artifactId);
      const expiresAt = now() + 15 * 60 * 1000;
      return json(200, { grants: ids.map((id) => ({ artifactId: id, uploadUrl: `https://objects.test/${id}?expires=${expiresAt}`, requiredHeaders: { "content-type": "application/octet-stream" } })) });
    }
    if (step === "seal") return json(200, view("SEALED"));
    return json(404, {});
  };
  return { calls, handler, setDeclared: (body: Record<string, unknown>) => { declared = body; }, failNext: (step: string, what: (() => Response) | "network") => { failures.set(step, [...(failures.get(step) ?? []), what]); }, json, view: () => view };
}

function deps(server: ReturnType<typeof fakeServer>, puts: string[] = [], putFailures: string[] = [], now: () => number = () => Date.now()): UploadFlowDeps {
  let counter = 0;
  return {
    fetch: ((url: string, init?: RequestInit) => server.handler(url, init)) as unknown as typeof fetch,
    put: async (grant, file, _signal, onBytes) => {
      onBytes(0);
      if (putFailures.includes(grant.artifactId)) { putFailures.splice(putFailures.indexOf(grant.artifactId), 1); throw new Error("PUT failed"); }
      const expiry = Number(new URL(grant.uploadUrl).searchParams.get("expires"));
      if (Number.isFinite(expiry) && now() >= expiry) throw new Error("expired upload grant");
      puts.push(`${grant.artifactId}:${file.name}`);
      onBytes(file.size);
    },
    uuid: () => `uuid-${++counter}`,
    now: () => new Date("2026-11-18T01:30:00.123Z"),
  };
}

const run = (session: UploadSession, events: UploadFlowEvent[] = []) => session.run(new AbortController().signal, (event) => events.push(event));

describe("UploadSession happy path", () => {
  it("creates the work order, registers, uploads both files and seals in order", async () => {
    const server = fakeServer();
    const puts: string[] = [];
    const events: UploadFlowEvent[] = [];
    const result = await run(new UploadSession(input(), deps(server, puts)), events);
    expect(result).toEqual({ workOrderId: "wo-1", submissionRef: REF, revision: 1 });
    expect(server.calls.map((call) => `${call.method} ${call.url.replace(/^.*(?=observation-work-orders)/, "")}`)).toEqual([
      "POST observation-work-orders",
      "GET observation-work-orders/wo-1/external-reconstruction-context",
      "POST observation-work-orders/wo-1/external-reconstruction-submissions-v3",
      `POST observation-work-orders/wo-1/external-reconstruction-submissions/${REF}/revisions/1/upload-grants`,
      `POST observation-work-orders/wo-1/external-reconstruction-submissions/${REF}/revisions/1/upload-grants`,
      `POST observation-work-orders/wo-1/external-reconstruction-submissions/${REF}/revisions/1/seal`,
    ]);
    expect(puts).toEqual(["ortho:ortho.tif", "dsm:dsm.tif"]);
    expect(events.filter((event) => event.type === "stage").map((event) => (event as { stage: string }).stage)).toEqual(["workOrder", "register", "upload", "seal"]);
    expect(events.filter((event) => event.type === "fileDone")).toHaveLength(2);
  });

  it("sends the continuity header on every mutation and a stable idempotency key on creation", async () => {
    const server = fakeServer();
    await run(new UploadSession(input(), deps(server)));
    const mutating = server.calls.filter((call) => call.method === "POST");
    expect(mutating.every((call) => call.headers["x-ksi-continuity-fingerprint"] === FP)).toBe(true);
    expect(server.calls[0]!.headers["Idempotency-Key"]).toMatch(/^site-upload-uuid-1$/);
    expect(server.calls[0]!.body).toEqual({ name: "북측 1차 구역 · 2026-11-18 자료", workAreaIds: [AREA], scheduleId: null, executionMode: "EXTERNAL_RECONSTRUCTION" });
  });

  it("uploads a single DSM without inventing an ortho", async () => {
    const server = fakeServer();
    const puts: string[] = [];
    await run(new UploadSession(input([dsm]), deps(server, puts)));
    expect(puts).toEqual(["dsm:dsm.tif"]);
    expect((server.calls[2]!.body as { artifacts: unknown[] }).artifacts).toHaveLength(1);
  });

  it("fetches fresh complete grants after an earlier file consumes more than the grant lifetime", async () => {
    let currentTime = Date.parse("2026-11-18T01:30:00.000Z");
    const server = fakeServer(() => currentTime);
    const puts: string[] = [];
    const timingDeps = deps(server, puts, [], () => currentTime);
    const session = new UploadSession(input(), {
      ...timingDeps,
      put: async (grant, file, signal, onBytes) => {
        await timingDeps.put(grant, file, signal, onBytes);
        if (grant.artifactId === "ortho") currentTime += 16 * 60 * 1000;
      },
    });

    const result = await run(session);

    expect(result).toMatchObject({ workOrderId: "wo-1", submissionRef: REF, revision: 1 });
    expect(puts).toEqual(["ortho:ortho.tif", "dsm:dsm.tif"]);
    const grants = server.calls.filter((call) => call.url.endsWith("/upload-grants"));
    expect(grants).toHaveLength(2);
    expect(grants[0]!.url).toBe(grants[1]!.url);
    expect(grants[0]!.body).toBeNull();
  });
});

describe("UploadSession retry safety", () => {
  it("retries a lost registration with the same keys and body and does not recreate the work order", async () => {
    const server = fakeServer();
    server.failNext("register", () => server.json(503, {}));
    const session = new UploadSession(input(), deps(server));
    const first = await run(session).catch((error: unknown) => error);
    expect(first).toBeInstanceOf(UploadFlowError);
    expect((first as UploadFlowError).ambiguous).toBe(true);
    expect((first as UploadFlowError).stage).toBe("register");
    await run(session);
    const creates = server.calls.filter((call) => call.url.endsWith("/observation-work-orders"));
    const registers = server.calls.filter((call) => call.url.endsWith("-submissions-v3"));
    expect(creates).toHaveLength(1);
    expect(registers).toHaveLength(2);
    expect(registers[1]!.body).toEqual(registers[0]!.body);
    expect(server.calls.filter((call) => call.url.endsWith("/external-reconstruction-context"))).toHaveLength(1);
  });

  it("reuses the creation key after a lost creation response", async () => {
    const server = fakeServer();
    server.failNext("create", "network");
    const session = new UploadSession(input(), deps(server));
    await expect(run(session)).rejects.toMatchObject({ stage: "workOrder", ambiguous: true });
    await run(session);
    const creates = server.calls.filter((call) => call.url.endsWith("/observation-work-orders"));
    expect(creates).toHaveLength(2);
    expect(creates[1]!.headers["Idempotency-Key"]).toBe(creates[0]!.headers["Idempotency-Key"]);
  });

  it("reuses the exact work-order body after a creation retry crosses Seoul midnight", async () => {
    const server = fakeServer();
    server.failNext("create", "network");
    const clock = { current: new Date("2026-11-17T14:59:00.000Z") };
    const session = new UploadSession(input(), { ...deps(server), now: () => clock.current });

    await expect(run(session)).rejects.toMatchObject({ stage: "workOrder", ambiguous: true });
    clock.current = new Date("2026-11-17T15:01:00.000Z");
    await run(session);

    const creates = server.calls.filter((call) => call.url.endsWith("/observation-work-orders"));
    expect(creates).toHaveLength(2);
    expect(creates[1]!.headers["Idempotency-Key"]).toBe(creates[0]!.headers["Idempotency-Key"]);
    expect(creates[1]!.body).toEqual(creates[0]!.body);
    expect(creates[0]!.body).toMatchObject({ name: "북측 1차 구역 · 2026-11-17 자료" });
  });

  it("re-uploads only the file that failed and seals once", async () => {
    const server = fakeServer();
    const puts: string[] = [];
    const session = new UploadSession(input(), deps(server, puts, ["dsm"]));
    await expect(run(session)).rejects.toMatchObject({ stage: "upload", ambiguous: true });
    expect(puts).toEqual(["ortho:ortho.tif"]);
    await run(session);
    expect(puts).toEqual(["ortho:ortho.tif", "dsm:dsm.tif"]);
    expect(server.calls.filter((call) => call.url.endsWith("/upload-grants"))).toHaveLength(3);
    expect(server.calls.filter((call) => call.url.endsWith("/seal"))).toHaveLength(1);
    expect(server.calls.filter((call) => call.url.endsWith("-submissions-v3"))).toHaveLength(1);
  });

  it("retries only the seal when its response was lost, without uploading again", async () => {
    const server = fakeServer();
    const puts: string[] = [];
    server.failNext("seal", "network");
    const session = new UploadSession(input(), deps(server, puts));
    await expect(run(session)).rejects.toMatchObject({ stage: "seal", ambiguous: true });
    await run(session);
    expect(puts).toHaveLength(2);
    expect(server.calls.filter((call) => call.url.endsWith("/upload-grants"))).toHaveLength(2);
    expect(server.calls.filter((call) => call.url.endsWith("/seal"))).toHaveLength(2);
  });

  it.each(["OBSERVATION_MISSING", "OBSERVATION_MISMATCH"] as const)("reuploads the same complete revision after seal confirms %s", async (code) => {
    const server = fakeServer();
    const puts: string[] = [];
    server.failNext("seal", () => server.json(422, { code }));
    const session = new UploadSession(input(), deps(server, puts));

    await expect(run(session)).rejects.toMatchObject({
      stage: "seal", ambiguous: false, recoveryCode: code, retrySameRevision: true,
      message: expect.stringContaining("같은 제출로 다시 시도하면 이 제출의 파일을 모두 다시 올립니다"),
    });
    expect(puts).toEqual(["ortho:ortho.tif", "dsm:dsm.tif"]);

    await run(session);

    expect(puts).toEqual(["ortho:ortho.tif", "dsm:dsm.tif", "ortho:ortho.tif", "dsm:dsm.tif"]);
    expect(server.calls.filter((call) => call.url.endsWith("-submissions-v3"))).toHaveLength(1);
    expect(server.calls.filter((call) => call.url.endsWith("/upload-grants"))).toHaveLength(4);
    expect(server.calls.filter((call) => call.url.endsWith("/seal"))).toHaveLength(2);
  });

  it("keeps confirmed files after an uncertain seal response even if it carries a storage code", async () => {
    const server = fakeServer();
    const puts: string[] = [];
    server.failNext("seal", () => server.json(503, { code: "OBSERVATION_MISSING" }));
    const session = new UploadSession(input(), deps(server, puts));

    await expect(run(session)).rejects.toMatchObject({ stage: "seal", ambiguous: true, retrySameRevision: false, recoveryCode: null });
    await run(session);

    expect(puts).toEqual(["ortho:ortho.tif", "dsm:dsm.tif"]);
    expect(server.calls.filter((call) => call.url.endsWith("/upload-grants"))).toHaveLength(2);
  });

  it("accepts an already sealed record returned for the same registration and skips uploads", async () => {
    const server = fakeServer();
    const puts: string[] = [];
    // Core는 첫 등록을 받아 봉인까지 마쳤지만 응답이 유실됐다.
    server.failNext("register", () => { server.setDeclared(server.calls.at(-1)!.body as Record<string, unknown>); return server.json(503, {}); });
    const session = new UploadSession(input(), deps(server, puts));
    await expect(run(session)).rejects.toMatchObject({ stage: "register", ambiguous: true });
    server.failNext("register", () => server.json(200, server.view()("SEALED")));
    const result = await run(session);
    expect(result.submissionRef).toBe(REF);
    expect(puts).toHaveLength(0);
    expect(server.calls.some((call) => call.url.endsWith("/upload-grants") || call.url.endsWith("/seal"))).toBe(false);
  });

  it("does not accept a sealed record for a different declaration", async () => {
    const server = fakeServer();
    server.failNext("register", () => { server.setDeclared({ ...(server.calls.at(-1)!.body as Record<string, unknown>), submissionId: "console-someone-else" }); return server.json(200, server.view()("SEALED")); });
    await expect(run(new UploadSession(input(), deps(server)))).rejects.toMatchObject({ stage: "register", ambiguous: true });
  });
});

describe("UploadSession refusals", () => {
  it.each([400, 413, 415, 422])("keeps the existing work order available after registration refusal %s", async (status) => {
    const server = fakeServer();
    server.failNext("register", () => server.json(status, {}));
    const attempt = run(new UploadSession(input(), deps(server)));
    await expect(attempt).rejects.toMatchObject({
      stage: "register", ambiguous: false, recoveryWorkOrderId: "wo-1",
      message: expect.not.stringContaining("같은 요청"),
    });
  });

  it.each([[401], [403], [404], [422]])("treats %s on creation as a definite refusal", async (status) => {
    const server = fakeServer();
    server.failNext("create", () => server.json(status, { detail: "x" }));
    const error = await run(new UploadSession(input(), deps(server))).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(UploadFlowError);
    expect((error as UploadFlowError).ambiguous).toBe(false);
    expect((error as UploadFlowError).stage).toBe("workOrder");
  });

  it.each([[500], [502], [503], [408], [429]])("treats %s as ambiguous, never as a definite refusal", async (status) => {
    const server = fakeServer();
    server.failNext("create", () => server.json(status, {}));
    await expect(run(new UploadSession(input(), deps(server)))).rejects.toMatchObject({ ambiguous: true });
  });

  it("stops on an account continuity mismatch without claiming the request was processed", async () => {
    const server = fakeServer();
    server.failNext("create", () => server.json(409, { code: "ACCOUNT_CONTINUITY_MISMATCH" }));
    const error = await run(new UploadSession(input(), deps(server))).catch((e: unknown) => e);
    expect((error as UploadFlowError).ambiguous).toBe(false);
    expect((error as UploadFlowError).message).toMatch(/계정이 바뀌어/);
  });

  it("does not trust a creation response for another scope", async () => {
    const server = fakeServer();
    server.failNext("create", () => server.json(201, { workOrderId: "wo-9", siteId: "other-site", workAreaIds: [AREA] }));
    await expect(run(new UploadSession(input(), deps(server)))).rejects.toMatchObject({ stage: "workOrder", ambiguous: true });
    expect(server.calls).toHaveLength(1);
  });

  it("does not register when the epoch response is for another work order", async () => {
    const server = fakeServer();
    server.failNext("context", () => server.json(200, { workOrderId: "wo-other", expectedEpochId: "epoch-1" }));
    await expect(run(new UploadSession(input(), deps(server)))).rejects.toMatchObject({ stage: "register", ambiguous: true });
    expect(server.calls.some((call) => call.url.endsWith("-submissions-v3"))).toBe(false);
  });

  it("refuses an invalid capture interval as definite before registering", async () => {
    const server = fakeServer();
    const bad = { ...input(), endedLocal: "2026-11-18T09:00" };
    await expect(run(new UploadSession(bad, deps(server)))).rejects.toMatchObject({ stage: "register", ambiguous: false });
    expect(server.calls.some((call) => call.url.endsWith("-submissions-v3"))).toBe(false);
  });

  it("does not upload when the grants do not match the registered files", async () => {
    const server = fakeServer();
    const puts: string[] = [];
    server.failNext("grants", () => server.json(200, { grants: [{ artifactId: "ortho", uploadUrl: "https://objects.test/o", requiredHeaders: {} }] }));
    await expect(run(new UploadSession(input(), deps(server, puts)))).rejects.toMatchObject({ stage: "upload", ambiguous: true });
    expect(puts).toHaveLength(0);
  });

  it("does not call a seal response a success when it is not the sealed record of this attempt", async () => {
    const server = fakeServer();
    server.failNext("seal", () => server.json(200, { submissionRef: REF, state: "REGISTERED" }));
    await expect(run(new UploadSession(input(), deps(server)))).rejects.toMatchObject({ stage: "seal", ambiguous: true });
  });

  it("propagates an abort instead of reporting a failure", async () => {
    const server = fakeServer();
    const controller = new AbortController();
    const session = new UploadSession(input(), { ...deps(server), fetch: (async () => { controller.abort(); throw new DOMException("aborted", "AbortError"); }) as unknown as typeof fetch });
    await expect(session.run(controller.signal, () => undefined)).rejects.toMatchObject({ name: "AbortError" });
  });
});
