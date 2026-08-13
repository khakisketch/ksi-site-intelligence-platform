import { describe, expect, it } from "vitest";

import {
  DIFF_CELL_COLOR,
  DIFF_CELL_LABEL,
  classifyDiffCell,
  conformanceReadySurfaces,
  declaredObservedRows,
  designComparableJobs,
  diffIntensity,
  isTerminalDesignSurfaceStatus,
  pendingVerification,
} from "@/lib/design-conformance";
import {
  DESIGN_SURFACE_REJECTION_LABEL,
  DESIGN_SURFACE_STATUS_LABEL,
  humanizeDesignSurfaceRejection,
  humanizeVerticalDatum,
} from "@/lib/core-api/labels";
import {
  DESIGN_SURFACE_REJECTION_REASONS,
  DESIGN_SURFACE_STATUSES,
  type DesignSurface,
  type SiteProcessingJobSummary,
} from "@/lib/core-api/types";

// 이 파일이 지키는 것은 하나다: **주장과 사실이 화면에서 갈라져 있는가.**
// 렌더링은 vitest 대상이 아니므로(jsdom 없음) 그 판정을 내리는 순수 함수와
// 라벨 표만 본다.

function surface(overrides: Partial<DesignSurface> = {}): DesignSurface {
  return {
    schemaVersion: "1.0",
    designSurfaceId: "SITE-1-ds1",
    siteId: "SITE-1",
    name: "A공구 계획고",
    revision: "Rev.C",
    format: "geotiff",
    declared: {
      crs: "EPSG:5186",
      lengthUnit: "meter",
      sha256: "a".repeat(64),
      verticalReference: {
        datum: "ellipsoidal",
        basis: "설계사 제공 도면 표제부에 타원체고 명시",
        source: "user_declared",
      },
    },
    observed: null,
    status: "REGISTERED",
    rejectionReason: null,
    registeredAt: "2026-08-12T00:00:00Z",
    registeredBy: "operator-1",
    sealedAt: null,
    verifiedAt: null,
    ...overrides,
  };
}

const OBSERVED: NonNullable<DesignSurface["observed"]> = {
  sha256: "a".repeat(64),
  crs: "EPSG:5186",
  verticalCrsEpsg: null,
  width: 1200,
  height: 900,
  bandCount: 1,
  dtype: "float32",
  nodata: null,
  nodataIsNan: true,
  pixelSizeXM: 0.25,
  pixelSizeYM: 0.25,
  transform: [0.25, 0, 200000, 0, -0.25, 500000],
  boundsMinX: 200000,
  boundsMinY: 499775,
  boundsMaxX: 200300,
  boundsMaxY: 500000,
  finiteCellCount: 1_080_000,
  measuredAt: "2026-08-12T00:05:00Z",
  measuredBy: "design-surface-verifier",
};

describe("검증이 끝난 설계면만 비교 입력이 된다", () => {
  it("[핵심] VERIFIED 가 아닌 것은 하나도 고를 수 없다", () => {
    const all: DesignSurface[] = [
      surface({ designSurfaceId: "ds-registered", status: "REGISTERED" }),
      surface({ designSurfaceId: "ds-sealed", status: "SEALED", sealedAt: "2026-08-12T00:01:00Z" }),
      surface({
        designSurfaceId: "ds-rejected",
        status: "REJECTED",
        sealedAt: "2026-08-12T00:01:00Z",
        rejectionReason: "CRS_DECLARATION_MISMATCH",
      }),
      surface({
        designSurfaceId: "ds-verified",
        status: "VERIFIED",
        sealedAt: "2026-08-12T00:01:00Z",
        verifiedAt: "2026-08-12T00:05:00Z",
        observed: OBSERVED,
      }),
    ];
    expect(conformanceReadySurfaces(all).map((s) => s.designSurfaceId)).toEqual(["ds-verified"]);
  });

  it("SEALED 는 '업로드했다는 주장'일 뿐이라 비교에 쓰이지 않는다", () => {
    const sealed = surface({ status: "SEALED", sealedAt: "2026-08-12T00:01:00Z" });
    expect(conformanceReadySurfaces([sealed])).toHaveLength(0);
  });
});

describe("판정 대기 여부", () => {
  it("SEALED 가 하나라도 있으면 판정을 기다린다", () => {
    expect(pendingVerification([surface({ status: "SEALED", sealedAt: "x" })])).toBe(true);
  });

  it("[핵심] REGISTERED 로는 기다리지 않는다 — 파일이 없어 서버가 할 일이 없다", () => {
    // 여기서 true 를 돌려주면 폴링이 영원히 멈추지 않는다.
    expect(pendingVerification([surface({ status: "REGISTERED" })])).toBe(false);
  });

  it("판정이 끝난 것들만 있으면 기다리지 않는다", () => {
    expect(
      pendingVerification([
        surface({ status: "VERIFIED", sealedAt: "x", verifiedAt: "y", observed: OBSERVED }),
        surface({ status: "REJECTED", sealedAt: "x", rejectionReason: "DIGEST_MISMATCH" }),
      ]),
    ).toBe(false);
  });

  it("종단 판정은 둘뿐이다", () => {
    expect(isTerminalDesignSurfaceStatus("VERIFIED")).toBe(true);
    expect(isTerminalDesignSurfaceStatus("REJECTED")).toBe(true);
    expect(isTerminalDesignSurfaceStatus("SEALED")).toBe(false);
    expect(isTerminalDesignSurfaceStatus("REGISTERED")).toBe(false);
  });
});

describe("현재 지형 후보", () => {
  function job(overrides: Partial<SiteProcessingJobSummary>): SiteProcessingJobSummary {
    return {
      jobId: "job-1",
      missionId: "M-1",
      siteId: "SITE-1",
      status: "SUCCEEDED",
      issuedAt: "2026-08-01T00:00:00Z",
      detail: null,
      artifacts: [{ artifactId: "dsm.tif", kind: "dsm" }],
      ...overrides,
    };
  }

  it("[핵심] 높이자료 없는 결과·다른 임무·미완료는 후보가 아니다", () => {
    const jobs = [
      job({ jobId: "ok", issuedAt: "2026-08-03T00:00:00Z" }),
      job({ jobId: "no-dsm", artifacts: [{ artifactId: "ortho.tif", kind: "ortho" }] }),
      job({ jobId: "other-mission", missionId: "M-2" }),
      job({ jobId: "running", status: "RUNNING" }),
    ];
    expect(designComparableJobs(jobs, "M-1").map((j) => j.jobId)).toEqual(["ok"]);
  });

  it("최신이 먼저 온다", () => {
    const jobs = [
      job({ jobId: "old", issuedAt: "2026-08-01T00:00:00Z" }),
      job({ jobId: "new", issuedAt: "2026-08-09T00:00:00Z" }),
    ];
    expect(designComparableJobs(jobs, "M-1").map((j) => j.jobId)).toEqual(["new", "old"]);
  });
});

describe("선언 vs 관측 대조표", () => {
  it("[핵심] 아직 재지 않았으면 관측 칸이 전부 비어 있다 — 선언값이 관측처럼 보이지 않는다", () => {
    const rows = declaredObservedRows(surface());
    expect(rows.every((row) => row.observed === null)).toBe(true);
    expect(rows.find((row) => row.label === "좌표계")?.declared).toBe("EPSG:5186");
  });

  it("측정이 끝나면 관측 칸이 채워진다", () => {
    const rows = declaredObservedRows(
      surface({ status: "VERIFIED", sealedAt: "x", verifiedAt: "y", observed: OBSERVED }),
    );
    expect(rows.find((row) => row.label === "좌표계")?.observed).toBe("EPSG:5186");
    expect(rows.find((row) => row.label === "격자 크기")?.observed).toBe("1200 × 900 화소");
  });

  it("파일에 수직 CRS 가 없는 것은 정상이라고 말한다 — 결함처럼 보이지 않게", () => {
    const rows = declaredObservedRows(
      surface({ status: "VERIFIED", sealedAt: "x", verifiedAt: "y", observed: OBSERVED }),
    );
    const row = rows.find((r) => r.label.startsWith("파일 안의 높이 기준"));
    expect(row?.observed).toContain("정상");
  });
});

describe("차분 래스터 3상태 분류", () => {
  const threshold = 0.05;

  it("[핵심] 모르는 셀은 0 이 아니라 '모름'이다", () => {
    expect(classifyDiffCell(null, threshold)).toBe("unknown");
    expect(classifyDiffCell(Number.NaN, threshold)).toBe("unknown");
    // 0 은 "차이가 없다"는 값이지 "모른다"가 아니다 — 둘이 같은 색이 되면
    // 지도가 확인된 적 없는 것을 "설계대로 됐다"고 말한다.
    expect(classifyDiffCell(0, threshold)).toBe("below-threshold");
  });

  it("문턱 미만은 집계에서 빠진 값으로 따로 분류된다", () => {
    expect(classifyDiffCell(0.049, threshold)).toBe("below-threshold");
    expect(classifyDiffCell(-0.049, threshold)).toBe("below-threshold");
  });

  it("[핵심] 부호가 방향이다 — 양수는 쌓아야 함, 음수는 깎아야 함", () => {
    // 값 규약은 `설계 표고 − 현재 표고` 다(계약 DiffRasterRef). 이 매핑이
    // 뒤집히면 지도가 절토와 성토를 정반대로 말한다.
    expect(classifyDiffCell(1.2, threshold)).toBe("fill");
    expect(classifyDiffCell(-1.2, threshold)).toBe("cut");
  });

  it("문턱 경계값은 집계에 포함된다(>= 기준)", () => {
    expect(classifyDiffCell(0.05, threshold)).toBe("fill");
    expect(classifyDiffCell(-0.05, threshold)).toBe("cut");
  });

  it("네 상태 전부 색과 문구를 갖는다 — 범례에 빈칸이 생기지 않는다", () => {
    for (const cell of ["unknown", "below-threshold", "fill", "cut"] as const) {
      expect(DIFF_CELL_COLOR[cell]).toMatch(/^#[0-9a-f]{6}$/i);
      expect(DIFF_CELL_LABEL[cell].length).toBeGreaterThan(0);
    }
    expect(new Set(Object.values(DIFF_CELL_COLOR)).size).toBe(4);
  });
});

describe("발산형 세기", () => {
  it("최대값에서 1, 절반에서 0.5", () => {
    expect(diffIntensity(2, 2)).toBe(1);
    expect(diffIntensity(1, 2)).toBe(0.5);
    expect(diffIntensity(-1, 2)).toBe(0.5);
  });

  it("[핵심] 기준이 없으면 흐리게 그리지 않는다 — 최댓값으로 고정한다", () => {
    expect(diffIntensity(1, 0)).toBe(1);
  });

  it("최대를 넘는 값도 1을 넘지 않는다", () => {
    expect(diffIntensity(9, 2)).toBe(1);
  });
});

describe("상태·거부 사유 한국어 문구", () => {
  it("[핵심] 상태 4종 전부 라벨이 있다", () => {
    for (const status of DESIGN_SURFACE_STATUSES) {
      expect(DESIGN_SURFACE_STATUS_LABEL[status].label.length).toBeGreaterThan(0);
      expect(DESIGN_SURFACE_STATUS_LABEL[status].description.length).toBeGreaterThan(0);
    }
  });

  it("[핵심] SEALED 를 '완료'라고 부르지 않는다 — 아무도 파일을 열어보지 않았다", () => {
    const sealed = DESIGN_SURFACE_STATUS_LABEL.SEALED;
    expect(sealed.label).not.toContain("완료");
    expect(sealed.description).toContain("주장");
  });

  it("거부 사유 8종 전부 사람 말 문구가 있다", () => {
    for (const reason of DESIGN_SURFACE_REJECTION_REASONS) {
      expect(DESIGN_SURFACE_REJECTION_LABEL[reason].length).toBeGreaterThan(0);
    }
  });

  it("[핵심] 모르는 사유는 숨기지 않고 원문을 남긴다", () => {
    expect(humanizeDesignSurfaceRejection("SOMETHING_NEW")).toContain("SOMETHING_NEW");
    expect(humanizeDesignSurfaceRejection(null)).toContain("기록되지 않았");
  });

  it("수직 기준은 사람 말로, 모르는 값은 원문 그대로", () => {
    expect(humanizeVerticalDatum("ellipsoidal_native")).toContain("타원체");
    expect(humanizeVerticalDatum("orthometric_kngeoid2018")).toContain("해발");
    expect(humanizeVerticalDatum("mystery_datum")).toBe("mystery_datum");
  });
});
