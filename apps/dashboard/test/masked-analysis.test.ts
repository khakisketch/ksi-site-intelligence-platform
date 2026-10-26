import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelMaskedCalculation,
  canonicalSubjectDigest,
  clearMaskedContinuity,
  createMaskedCalculation,
  declareMaskChild,
  getMaskChild,
  getMaskedCalculation,
  getMaskInspectionStatus,
  getMaskSourceContext,
  maskedContinuityKey,
  maskedErrorCode,
  MaskedConflictError,
  MaskedNotFoundError,
  MaskedRequestError,
  MaskedUpstreamTimeoutError,
  parseMaskChildDeclaration,
  parseMaskChildView,
  parseMaskedCalculationCreate,
  parseMaskedCalculationCreated,
  parseMaskedCalculationDetail,
  parseMaskedDeltaSourceRef,
  parseMaskedSourceContext,
  parseMaskInspectionStatusView,
  parseMaskUploadGrantRequest,
  parseMaskUploadSealView,
  readMaskedContinuity,
  requestMaskUploadGrant,
  uploadMaskBytes,
  validateMaskFile,
  writeMaskedContinuity,
  type MaskChildDeclarationWire,
  type MaskChildViewWire,
  type MaskedCalculationDetailWire,
  type MaskedContinuityScope,
} from "@/lib/core-api/masked-analysis";

const fixture = JSON.parse(
  readFileSync("test/masked-wire-fixture.json", "utf-8"),
) as Record<string, unknown>;

const scope = { siteId: "site-1", workAreaId: "area-1" };
const childScope = { ...scope, maskChildId: "mask-child-1" };

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

describe("정규 subject 확인값", () => {
  it("TS 정규화가 Core canonical_digest와 바이트 단위로 같다", async () => {
    const parent = fixture.parentSubject as Parameters<typeof canonicalSubjectDigest>[0];
    const baseline = fixture.baselineSubject as Parameters<typeof canonicalSubjectDigest>[0];
    const manifest = fixture.manifest as { parentSubjectDigest: string; targetBaselineSubjectDigest: string };
    await expect(canonicalSubjectDigest(parent)).resolves.toBe(manifest.parentSubjectDigest);
    await expect(canonicalSubjectDigest(baseline)).resolves.toBe(manifest.targetBaselineSubjectDigest);
  });
});

describe("parseMaskChildDeclaration", () => {
  it("실제 계약 선언 와이어를 그대로 받는다", () => {
    expect(parseMaskChildDeclaration(fixture.declaration)).toEqual(fixture.declaration);
  });

  it("부모가 기준과 같은 subject여도 받는다(서로 다름을 요구하지 않는다)", () => {
    const declaration = clone(fixture.declaration) as MaskChildDeclarationWire;
    declaration.parentSubject = declaration.targetBaselineSubject;
    expect(parseMaskChildDeclaration(declaration).parentSubject).toEqual(declaration.targetBaselineSubject);
  });

  it("범위를 벗어난 subject를 버린다", () => {
    const declaration = clone(fixture.declaration) as MaskChildDeclarationWire;
    declaration.parentSubject = { ...declaration.parentSubject, siteId: "site-9" };
    expect(() => parseMaskChildDeclaration(declaration)).toThrow(MaskedRequestError);
  });

  it("격자 필드가 섞이면 버린다", () => {
    expect(() => parseMaskChildDeclaration({ ...(fixture.declaration as object), rows: 4 })).toThrow(MaskedRequestError);
  });
});

describe("parseMaskChildView", () => {
  it("대기(선언만)·완료(봉인 manifest) 화면을 받는다", () => {
    const pending = parseMaskChildView(fixture.childViewPending, childScope);
    expect(pending.manifest).toBeNull();
    const ready = parseMaskChildView(fixture.childViewReady, childScope) as MaskChildViewWire;
    expect(ready.manifest?.manifestDigest).toBe((fixture.manifest as { manifestDigest: string }).manifestDigest);
  });

  it("자식 메아리가 다르면 버린다", () => {
    expect(() => parseMaskChildView(fixture.childViewReady, { ...childScope, maskChildId: "other" })).toThrow();
  });
});

describe("grant/seal", () => {
  it("부여 요청 와이어를 받는다(ttl 생략·포함)", () => {
    const request = fixture.grantRequest as Record<string, unknown>;
    expect(parseMaskUploadGrantRequest(request)).toEqual({ ...request });
    expect(parseMaskUploadGrantRequest(request).ttlSeconds).toBe(3600);
    expect(parseMaskUploadGrantRequest({ ...request, ttlSeconds: 600 })).toEqual({ ...request, ttlSeconds: 600 });
    expect(() => parseMaskUploadGrantRequest({ ...request, ttlSeconds: 0 })).toThrow(MaskedRequestError);
    expect(() => parseMaskUploadGrantRequest({ ...request, gridRows: 4 })).toThrow(MaskedRequestError);
  });

  it("봉인 화면이 선언 값과 메아리된다", () => {
    const view = parseMaskUploadSealView(fixture.sealView, {
      maskChildId: "mask-child-1",
      maskArtifactId: "mask-artifact-1",
      declaredSha256: (fixture.declaration as { declaredSha256: string }).declaredSha256,
      declaredSizeBytes: 2,
    });
    expect(view.observedSizeBytes).toBe(2);
    expect(() => parseMaskUploadSealView(fixture.sealView, {
      maskChildId: "mask-child-1",
      maskArtifactId: "mask-artifact-1",
      declaredSha256: `sha256:${"9".repeat(64)}`,
      declaredSizeBytes: 2,
    })).toThrow();
  });
});

describe("생성/화면", () => {
  it("생성은 원본 신원+자식만 받는다(바인딩 확인값 키가 섞이면 버린다)", () => {
    expect(parseMaskedCalculationCreate(fixture.createRequest)).toEqual(fixture.createRequest);
    expect(() => parseMaskedCalculationCreate({ ...(fixture.createRequest as object), maskBindingDigest: `sha256:${"1".repeat(64)}` }))
      .toThrow(MaskedRequestError);
  });

  it("생성 응답을 범위 메아리로 받는다", () => {
    const created = parseMaskedCalculationCreated(fixture.createdView, scope);
    expect(created.admission.disposition).toBe("ADMIT_PROVISIONAL");
  });

  it("AVAILABLE 화면은 봉인 보고서를 싣는다", () => {
    const detail = parseMaskedCalculationDetail(fixture.detailViewAvailable, {
      ...scope,
      requestId: "req-v3-1",
    }) as MaskedCalculationDetailWire;
    expect(detail.report?.numericResult.metrics.netM3).toBe(4);
    expect(detail.report?.numericResult.coverage.commonValidCellCount).toBe(12);
  });

  it("PENDING 화면은 보고서 없이 온다", () => {
    const detail = parseMaskedCalculationDetail(fixture.detailViewPending, { ...scope, requestId: "req-v3-1" });
    expect(detail.report).toBeNull();
    expect(detail.disposition).toBe("PENDING");
  });

  it("알 수 없는 impact는 전부 null이다", () => {
    const detail = parseMaskedCalculationDetail(fixture.detailViewUnknownImpact, { ...scope, requestId: "req-v3-2" });
    const impact = detail.report?.numericResult.impact;
    expect(impact?.unmaskedImpactKnown).toBe(false);
    expect([impact?.unmaskedCutM3, impact?.excludedNetM3]).toEqual([null, null]);
  });

  it("순변화 ≠ 성토−절토이면 버린다", () => {
    const tampered = clone(fixture.detailViewAvailable) as typeof fixture.detailViewAvailable & {
      report: { numericResult: { metrics: { netM3: number } } };
    };
    tampered.report.numericResult.metrics.netM3 = 5;
    expect(() => parseMaskedCalculationDetail(tampered, { ...scope, requestId: "req-v3-1" })).toThrow();
  });

  it("커버리지 개수가 비트와 어긋나면 버린다", () => {
    const tampered = clone(fixture.detailViewAvailable) as typeof fixture.detailViewAvailable & {
      report: { numericResult: { coverage: { effectiveSelectedCellCount: number } } };
    };
    tampered.report.numericResult.coverage.effectiveSelectedCellCount = 10;
    expect(() => parseMaskedCalculationDetail(tampered, { ...scope, requestId: "req-v3-1" })).toThrow();
  });

  it("알 수 없음인데 부피가 있으면 버린다", () => {
    const tampered = clone(fixture.detailViewUnknownImpact) as typeof fixture.detailViewUnknownImpact & {
      report: { numericResult: { impact: { excludedCutM3: number | null } } };
    };
    tampered.report.numericResult.impact.excludedCutM3 = 0;
    expect(() => parseMaskedCalculationDetail(tampered, { ...scope, requestId: "req-v3-2" })).toThrow();
  });

  it("PENDING인데 보고서를 싣거나 AVAILABLE인데 보고서가 없으면 버린다", () => {
    const pending = clone(fixture.detailViewPending) as Record<string, unknown>;
    const available = clone(fixture.detailViewAvailable) as Record<string, unknown>;
    pending.report = (fixture.detailViewAvailable as { report: unknown }).report;
    (available.report as { numericResult: unknown } | null) = null;
    expect(() => parseMaskedCalculationDetail(pending, { ...scope, requestId: "req-v3-1" })).toThrow();
    expect(() => parseMaskedCalculationDetail(available, { ...scope, requestId: "req-v3-1" })).toThrow();
  });

  it("여분 키·범위 메아리 불일치를 버린다", () => {
    expect(() => parseMaskedCalculationDetail(
      { ...(fixture.detailViewAvailable as object), gridRows: 4 },
      { ...scope, requestId: "req-v3-1" },
    )).toThrow();
    expect(() => parseMaskedCalculationDetail(fixture.detailViewAvailable, { ...scope, requestId: "req-other" })).toThrow();
  });

  it("AVAILABLE인데 봉인이 풀린 확인값이 있으면 버린다(해시 재계산 없음)", () => {
    const noReportDigest = clone(fixture.detailViewAvailable) as {
      report: { reportDigest: string | null };
    };
    noReportDigest.report.reportDigest = null;
    expect(() => parseMaskedCalculationDetail(noReportDigest, { ...scope, requestId: "req-v3-1" })).toThrow();
    const noNumericDigest = clone(fixture.detailViewAvailable) as {
      report: { numericResult: { numericResultIdentityDigest: string | null } };
    };
    noNumericDigest.report.numericResult.numericResultIdentityDigest = null;
    expect(() => parseMaskedCalculationDetail(noNumericDigest, { ...scope, requestId: "req-v3-1" })).toThrow();
    const noCoverageDigest = clone(fixture.detailViewAvailable) as {
      report: { numericResult: { coverage: { coverageWitnessDigest: string | null } } };
    };
    noCoverageDigest.report.numericResult.coverage.coverageWitnessDigest = null;
    expect(() => parseMaskedCalculationDetail(noCoverageDigest, { ...scope, requestId: "req-v3-1" })).toThrow();
  });
});

describe("인계 참조", () => {
  it("실제 계약 인계 와이어를 받는다", () => {
    expect(parseMaskedDeltaSourceRef(fixture.deltaSourceRef)).toEqual(fixture.deltaSourceRef);
  });
});

describe("validateMaskFile", () => {
  const tiff = (name: string, size: number, type = "image/tiff") =>
    ({ name, size, type }) as File;

  it("예산이 없으면 선택 자체를 막는다", () => {
    expect(validateMaskFile(tiff("mask.tif", 100), null)).toMatch(/예산/);
  });

  it("tif/tiff만 예산 안에서 받는다", () => {
    expect(validateMaskFile(tiff("mask.png", 100, "image/png"), 1024)).not.toBeNull();
    expect(validateMaskFile(tiff("mask.tif", 100), 1024)).toBeNull();
    expect(validateMaskFile(tiff("mask.tif", 2048), 1024)).not.toBeNull();
  });
});

describe("원본 맥락", () => {
  const digest = fixture.sourceCalculationIdentityDigest as string;
  const context = fixture.sourceContext as Record<string, unknown>;

  it("실제 계약 10키 와이어를 그대로 받는다", () => {
    expect(parseMaskedSourceContext(context, { ...scope, sourceCalculationIdentityDigest: digest })).toEqual(context);
  });

  it("부모가 기준과 같은 subject여도 받는다(서로 다름을 요구하지 않는다)", () => {
    const same = { ...context, currentSubject: context.baselineSubject };
    expect(parseMaskedSourceContext(same, { ...scope, sourceCalculationIdentityDigest: digest }).currentSubject)
      .toEqual(context.baselineSubject);
  });

  it("여분 키·범위 메아리 불일치를 버린다", () => {
    expect(() => parseMaskedSourceContext({ ...context, gridRows: 4 }, { ...scope, sourceCalculationIdentityDigest: digest }))
      .toThrow();
    expect(() => parseMaskedSourceContext(context, { ...scope, sourceCalculationIdentityDigest: `sha256:${"9".repeat(64)}` }))
      .toThrow();
  });

  it("현장이 다른 subject·승인 상태를 버린다", () => {
    const foreign = {
      ...context,
      baselineSubject: { ...(context.baselineSubject as object), siteId: "site-9" },
    };
    expect(() => parseMaskedSourceContext(foreign, { ...scope, sourceCalculationIdentityDigest: digest })).toThrow();
    expect(() => parseMaskedSourceContext({ ...context, sourceDisposition: "BLOCKED" }, { ...scope, sourceCalculationIdentityDigest: digest }))
      .toThrow();
  });

  it("클라이언트는 snake 쿼리로 BFF에 싣는다", async () => {
    const seen: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      seen.push(String(input));
      return new Response(JSON.stringify(context), { headers: { "content-type": "application/json" } });
    }));
    const view = await getMaskSourceContext("site-1", "area-1", digest);
    expect(view.maxMaskBytes).toBe(8388608);
    expect(seen).toEqual([
      `/api/sites/site-1/work-areas/area-1/mask-inputs/source-context?source_calculation_identity_digest=${encodeURIComponent(digest)}`,
    ]);
  });

  it("오류 코드는 가리지 않고 싣는다", () => {
    const error = new MaskedConflictError("펜스 만료");
    error.code = "MASKED_INPUT_FENCE_REJECTED";
    expect(maskedErrorCode(error)).toBe("MASKED_INPUT_FENCE_REJECTED");
    expect(maskedErrorCode(new Error("x"))).toBeNull();
  });
});

describe("작업 연속성", () => {
  const scope: MaskedContinuityScope = {
    organizationId: "org-1",
    principalId: "op-1",
    siteId: "site-1",
    workAreaId: "area-1",
    sourceCalculationIdentityDigest: fixture.sourceCalculationIdentityDigest as string,
  };

  function memoryStorage() {
    const map = new Map<string, string>();
    return {
      getItem: (key: string) => (map.has(key) ? map.get(key)! : null),
      setItem: (key: string, value: string) => { map.set(key, value); },
      removeItem: (key: string) => { map.delete(key); },
      raw: map,
    };
  }

  it("저장소가 없으면 읽지 않고 쓰지 않는다", () => {
    expect(readMaskedContinuity(scope)).toBeNull();
    expect(writeMaskedContinuity(scope, { maskChildId: "mask-1", requestId: null })).toBe(false);
  });

  it("키는 범위마다 안정적이며 사용자를 가른다", () => {
    expect(maskedContinuityKey(scope)).toBe(maskedContinuityKey({ ...scope }));
    expect(maskedContinuityKey(scope)).not.toBe(
      maskedContinuityKey({ ...scope, principalId: "op-2" }),
    );
    expect(() => maskedContinuityKey({ ...scope, principalId: "" })).toThrow();
  });

  it("불투명 id만 왕복하고 형식이 어긋나면 지운다", () => {
    const storage = memoryStorage();
    vi.stubGlobal("sessionStorage", storage);
    try {
      expect(writeMaskedContinuity(scope, { maskChildId: "mask-child-1", requestId: "req-v3-1" })).toBe(true);
      expect(readMaskedContinuity(scope)).toEqual({
        version: 1,
        scope,
        maskChildId: "mask-child-1",
        requestId: "req-v3-1",
      });
      storage.setItem(maskedContinuityKey(scope), "{malformed");
      expect(readMaskedContinuity(scope)).toBeNull();
      expect(storage.raw.has(maskedContinuityKey(scope))).toBe(false);
      storage.setItem(maskedContinuityKey(scope), "x".repeat(4096));
      expect(readMaskedContinuity(scope)).toBeNull();
      expect(storage.raw.has(maskedContinuityKey(scope))).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("안의 범위가 다르면 읽지 않고 지운다", () => {
    const storage = memoryStorage();
    vi.stubGlobal("sessionStorage", storage);
    try {
      const key = maskedContinuityKey(scope);
      storage.setItem(key, JSON.stringify({
        version: 1,
        scope: { ...scope, principalId: "op-2" },
        maskChildId: "mask-child-1",
        requestId: null,
      }));
      expect(readMaskedContinuity(scope)).toBeNull();
      expect(storage.raw.has(key)).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("불투명하지 않은 id·초과분은 쓰지 않는다", () => {
    const storage = memoryStorage();
    vi.stubGlobal("sessionStorage", storage);
    try {
      expect(writeMaskedContinuity(scope, { maskChildId: "https://x/m", requestId: null })).toBe(false);
      expect(writeMaskedContinuity(scope, { maskChildId: "mask-1", requestId: "req 1" })).toBe(false);
      expect(readMaskedContinuity(scope)).toBeNull();
      clearMaskedContinuity(scope);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("검사 상태", () => {
  const childScope = { siteId: "site-1", workAreaId: "area-1", maskChildId: "mask-child-1" };

  it("실제 계약 와이어를 받는다(완료·거부·실패·대기)", () => {
    expect(parseMaskInspectionStatusView(fixture.inspectionCompleted, { ...childScope, maskChildId: "mask-child-1" }).status).toBe("COMPLETED");
    const rejected = parseMaskInspectionStatusView(
      { ...(fixture.inspectionRejected as object), maskChildId: "mask-child-1" },
      childScope,
    );
    expect(rejected.reasonCode).toBe("MASK_NODATA_REJECTED");
    const failed = parseMaskInspectionStatusView(
      { ...(fixture.inspectionFailed as object), maskChildId: "mask-child-1" },
      childScope,
    );
    expect(failed.status).toBe("FAILED");
    expect(parseMaskInspectionStatusView(
      { ...(fixture.inspectionPending as object), maskChildId: "mask-child-1" },
      childScope,
    ).status).toBe("PENDING");
  });

  it("terminal 사유·봉인 조합을 강제한다", () => {
    expect(() => parseMaskInspectionStatusView(
      { ...(fixture.inspectionRejected as object), maskChildId: "mask-child-1", reasonCode: null },
      childScope,
    )).toThrow();
    expect(() => parseMaskInspectionStatusView(
      { ...(fixture.inspectionPending as object), maskChildId: "mask-child-1", reasonCode: "MASK_NODATA_REJECTED" },
      childScope,
    )).toThrow();
    expect(() => parseMaskInspectionStatusView(
      { ...(fixture.inspectionCompleted as object), manifestDigest: null },
      { ...childScope, maskChildId: "mask-child-1" },
    )).toThrow();
    expect(() => parseMaskInspectionStatusView(
      { ...(fixture.inspectionRejected as object), maskChildId: "mask-child-1", manifestDigest: `sha256:${"1".repeat(64)}` },
      childScope,
    )).toThrow();
    expect(() => parseMaskInspectionStatusView(
      { ...(fixture.inspectionCompleted as object), status: "DONE" },
      { ...childScope, maskChildId: "mask-child-1" },
    )).toThrow();
  });

  it("범위 메아리·UTC를 검증한다", () => {
    expect(() => parseMaskInspectionStatusView(fixture.inspectionCompleted, { ...childScope, maskChildId: "other" })).toThrow();
    expect(() => parseMaskInspectionStatusView(
      { ...(fixture.inspectionCompleted as object), maskChildId: "mask-child-1", checkedAt: "2026-10-26 00:10:00" },
      childScope,
    )).toThrow();
  });

  it("클라이언트는 고정 자식 경로로 싣는다", async () => {
    const seen: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      seen.push(String(input));
      return new Response(JSON.stringify({ ...(fixture.inspectionCompleted as object), maskChildId: "mask-child-1" }), {
        headers: { "content-type": "application/json" },
      });
    }));
    try {
      const view = await getMaskInspectionStatus("site-1", "area-1", "mask-child-1");
      expect(view.status).toBe("COMPLETED");
      expect(seen).toEqual(["/api/sites/site-1/work-areas/area-1/mask-inputs/mask-child-1/inspection-status"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("실제 브라우저 Core 페이로드", () => {
  const actual = JSON.parse(
    readFileSync("test/masked-browser-core-detail.json", "utf-8"),
  ) as Record<string, unknown>;
  const actualScope = { siteId: "site-a", workAreaId: "wa-site-a-0001", requestId: "req-b3e57ffd-60d9-4771-ad4e-bbf97ebee791" };

  it("실제 AVAILABLE 화면을 닫힌 형태로 받는다(음수 오프셋 포함)", () => {
    const detail = parseMaskedCalculationDetail(actual, actualScope);
    expect(detail.disposition).toBe("AVAILABLE");
    expect(detail.status).toBe("COMPLETED");
    const coverage = detail.report!.numericResult.coverage;
    expect([coverage.rowOffset, coverage.columnOffset]).toEqual([-1, -1]);
    expect([
      coverage.originalSelectedCellCount,
      coverage.maskExcludedCellCount,
      coverage.effectiveSelectedCellCount,
      coverage.commonValidCellCount,
      coverage.unavailableCellCount,
    ]).toEqual([4, 1, 3, 3, 0]);
    expect(coverage.cellAreaM2).toBeCloseTo(0.01, 12);
    // 세 확인값 교차 바인딩 — 수치·범위·보고서가 같은 계산을 가리킨다.
    const numeric = detail.report!.numericResult;
    expect(detail.report!.numericResultIdentityDigest).toBe(numeric.numericResultIdentityDigest);
    expect(numeric.coverage.coverageWitnessDigest).not.toBeNull();
    expect(numeric.maskedCalculationIdentityDigest).toBe(detail.maskedCalculationIdentityDigest);
    expect(detail.report!.maskedCalculationIdentityDigest).toBe(detail.maskedCalculationIdentityDigest);
    // 승인 신원이 화면 신원과 묶인다.
    expect(detail.admission!.maskedCalculationIdentityDigest).toBe(detail.maskedCalculationIdentityDigest);
    expect(detail.admission!.maskBindingDigest).toBe(numeric.maskBindingDigest);
    expect(detail.admission!.maskedProfileDigest).toBe(numeric.maskedProfileDigest);
  });

  it("소수·비유한 오프셋은 격자가 아니라서 버린다", () => {
    const tampered = JSON.parse(JSON.stringify(actual)) as {
      report: { numericResult: { coverage: { rowOffset: unknown; columnOffset: unknown } } };
    };
    tampered.report.numericResult.coverage.rowOffset = 1.5;
    expect(() => parseMaskedCalculationDetail(tampered, actualScope)).toThrow();
    tampered.report.numericResult.coverage.rowOffset = -1;
    tampered.report.numericResult.coverage.columnOffset = Number.NaN;
    expect(() => parseMaskedCalculationDetail(tampered, actualScope)).toThrow();
    tampered.report.numericResult.coverage.columnOffset = "-1";
    expect(() => parseMaskedCalculationDetail(tampered, actualScope)).toThrow();
  });
});

describe("BFF 클라이언트", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  function jsonResponse(value: unknown, status = 200): Response {
    return new Response(JSON.stringify(value), {
      status,
      headers: { "content-type": "application/json" },
    });
  }

  it("임포트만으로 요청하지 않는다", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("선언→부여→조회→생성→화면→취소를 실제 와이어로 왕복한다", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      const url = String(input);
      calls.push(url);
      if (url.endsWith("/mask-inputs") && !url.includes("upload")) return jsonResponse(fixture.childViewPending, 201);
      if (url.endsWith("/upload-grants")) return jsonResponse(fixture.grantView, 201);
      if (url.includes("/bytes")) return jsonResponse(fixture.sealView, 201);
      if (url.includes("/mask-inputs/")) return jsonResponse(fixture.childViewReady);
      if (url.endsWith("/masked-analyses")) return jsonResponse(fixture.createdView, 202);
      if (url.endsWith("/cancel")) return jsonResponse({ requestId: "req-v3-1", status: "CANCELED", attempt: null });
      return jsonResponse(fixture.detailViewAvailable);
    }));
    const declared = await declareMaskChild("site-1", "area-1", fixture.declaration as MaskChildDeclarationWire);
    expect(declared.manifest).toBeNull();
    const subjectDigest = await canonicalSubjectDigest(
      (fixture.declaration as MaskChildDeclarationWire).parentSubject,
    );
    const grant = await requestMaskUploadGrant("site-1", "area-1", "mask-child-1", {
      maskArtifactId: "mask-artifact-1",
      subjectDigest,
      declaredSha256: (fixture.declaration as { declaredSha256: string }).declaredSha256,
      declaredSizeBytes: 2,
    });
    expect(grant.grantId).toBe("grant-1");
    const child = await getMaskChild("site-1", "area-1", "mask-child-1");
    expect((child as MaskChildViewWire).manifest?.rows).toBe(4);
    const created = await createMaskedCalculation("site-1", "area-1", fixture.createRequest as Parameters<typeof createMaskedCalculation>[2]);
    expect(created.requestId).toBe("req-v3-1");
    const detail = await getMaskedCalculation("site-1", "area-1", "req-v3-1");
    expect(detail.disposition).toBe("AVAILABLE");
    const canceled = await cancelMaskedCalculation("site-1", "area-1", "req-v3-1");
    expect(canceled.status).toBe("CANCELED");
    expect(calls.length).toBe(6);
  });

  it("raw 업로드가 검증된 확인 정보 3종과 바이트를 함께 싣는다", async () => {
    let seenHeaders: Record<string, string> | null = null;
    vi.stubGlobal("fetch", vi.fn(async (_input: unknown, init?: { headers?: Record<string, string>; body?: unknown }) => {
      seenHeaders = init?.headers ?? null;
      return jsonResponse(fixture.sealView, 201);
    }));
    const file = new File([new Uint8Array([0xff, 0x00])], "mask.tif", { type: "image/tiff" });
    const expected = {
      maskArtifactId: "mask-artifact-1",
      declaredSha256: (fixture.declaration as { declaredSha256: string }).declaredSha256,
      declaredSizeBytes: 2,
    };
    const seal = await uploadMaskBytes("site-1", "area-1", "mask-child-1", "grant-1", file, expected);
    expect(seal.observedSizeBytes).toBe(2);
    // BFF가 요구하는 파일 확인 정보 3종이 파일의 선언 값과 바이트 단위로 같다.
    expect(seenHeaders?.["content-type"]).toBe("application/octet-stream");
    expect(seenHeaders?.["x-masked-artifact-id"]).toBe(expected.maskArtifactId);
    expect(seenHeaders?.["x-masked-declared-sha256"]).toBe(expected.declaredSha256);
    expect(seenHeaders?.["x-masked-declared-size-bytes"]).toBe(String(expected.declaredSizeBytes));
    expect(expected.declaredSizeBytes).toBe(file.size);
    // 같은 값으로 서버 봉인 응답이 교차 바인딩된다.
    expect(seal.maskArtifactId).toBe(expected.maskArtifactId);
    expect(seal.observedSha256).toBe(expected.declaredSha256);
    expect(seal.observedSizeBytes).toBe(expected.declaredSizeBytes);
  });

  it("검증되지 않은 확인 정보로는 업로드하지 않는다", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const file = new File([new Uint8Array([0xff, 0x00])], "mask.tif", { type: "image/tiff" });
    await expect(uploadMaskBytes("site-1", "area-1", "mask-child-1", "grant-1", file, {
      maskArtifactId: "https://x/mask",
      declaredSha256: (fixture.declaration as { declaredSha256: string }).declaredSha256,
      declaredSizeBytes: 2,
    })).rejects.toBeInstanceOf(MaskedRequestError);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("404·409·취소를 typed 오류로 닫는다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ message: "없음" }, 404)));
    await expect(getMaskedCalculation("site-1", "area-1", "req-v3-1")).rejects.toBeInstanceOf(MaskedNotFoundError);
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ message: "펜스 만료" }, 409)));
    await expect(getMaskedCalculation("site-1", "area-1", "req-v3-1")).rejects.toBeInstanceOf(MaskedConflictError);
    vi.stubGlobal("fetch", vi.fn(async (_input: unknown, init?: { signal?: AbortSignal }) => {
      await new Promise((resolve) => setTimeout(resolve, 50));
      if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");
      return jsonResponse(fixture.detailViewAvailable);
    }));
    const controller = new AbortController();
    const pending = getMaskedCalculation("site-1", "area-1", "req-v3-1", { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toBeInstanceOf(MaskedUpstreamTimeoutError);
  });
});
