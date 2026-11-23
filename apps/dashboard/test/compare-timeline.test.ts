import { describe, expect, it } from "vitest";

import { ANALYSIS_CRS_HINT, buildCompareTimeline, shortCrs } from "@/app/sites/[siteId]/compare-timeline";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import { ANALYSIS_CRS } from "@/lib/geo/known-crs";
import type { WorkspaceObservationFact, WorkspaceServerFacts } from "@/lib/site-workspace-entry";

const AREA = "area-1";
const ref = (n: number) => `ksa-v1-${String(n).padStart(64, "0")}`;

type FactOptions = Partial<WorkspaceObservationFact> & { n: number };

function fact({ n, ...rest }: FactOptions): WorkspaceObservationFact {
  return {
    observationEpochId: `epoch-${n}`,
    workAreaId: AREA,
    workOrderId: `wo-${n}`,
    assetRef: ref(n),
    submissionRef: `sub-${n}`,
    revision: 1,
    kind: "dsm",
    captureStartedAt: null,
    captureEndedAt: null,
    captureDate: null,
    displayReady: true,
    inspectedRasterAvailable: true,
    chronologyCandidate: true,
    captureSourcesAgree: true,
    viewAvailable: true,
    viewUnavailableReason: null,
    viewAssetRef: ref(n),
    newerRevisionPending: false,
    newerRevisionState: null,
    ...rest,
  };
}

/** 한국 시간 `date`의 한 시간짜리 촬영 구간. */
function interval(date: string, hour = 10): Partial<WorkspaceObservationFact> {
  const start = new Date(`${date}T${String(hour).padStart(2, "0")}:00:00+09:00`);
  const end = new Date(start.getTime() + 3_600_000);
  return { captureStartedAt: start.toISOString(), captureEndedAt: end.toISOString() };
}

function catalog(n: number, crs: string | null, kind = "dsm"): SpatialAssetCatalogItem {
  return {
    assetRef: ref(n),
    kind,
    lifecycleState: "SEALED",
    declared: { captureDate: null, captureStartedAt: null },
    inspection: {
      outcome: crs ? "MEASURED" : "FAILED",
      raster: crs ? { observedCrsIdentifier: crs } : null,
    },
  } as unknown as SpatialAssetCatalogItem;
}

function facts(list: WorkspaceObservationFact[], entryDefault: WorkspaceServerFacts["entryDefault"] = null): WorkspaceServerFacts {
  return { siteId: "site-1", authorizedWorkAreaIds: [AREA], entryDefault, observations: list, analyses: [] };
}

const FIVE = [
  fact({ n: 1, ...interval("2026-07-03") }),
  fact({ n: 2, ...interval("2026-08-21") }),
  fact({ n: 3, kind: "ortho", ...interval("2026-09-11") }),
  fact({ n: 4, ...interval("2026-10-02") }),
  fact({ n: 5, ...interval("2026-11-12") }),
];
const FIVE_CATALOG = [catalog(1, "EPSG:32652"), catalog(2, "EPSG:5186"), catalog(3, "EPSG:5186", "ortho"), catalog(4, "EPSG:5186"), catalog(5, "EPSG:5186")];

function build(overrides: Partial<Parameters<typeof buildCompareTimeline>[0]> = {}) {
  return buildCompareTimeline({ facts: facts(FIVE), workAreaId: AREA, catalogAssets: FIVE_CATALOG, ...overrides });
}

const pointOf = (model: ReturnType<typeof build>, n: number) =>
  model.slots.flatMap((slot) => slot.points).find((point) => point.assetRef === ref(n))!;

describe("buildCompareTimeline", () => {
  it("OK: 다섯 관측에서 흐림 이유와 기준 좌표계, 이전·이후, 일수를 만든다", () => {
    const model = build({ baselineAssetRef: ref(4), currentAssetRef: ref(5) });
    expect(model.status).toBe("OK");
    expect(model.referenceCrs).toBe("EPSG:5186");
    expect(model.referenceSwatch).toBe(1);
    expect(pointOf(model, 1).dimmed).toBe("crs-different");
    expect(pointOf(model, 3).dimmed).toBe("no-height");
    expect(pointOf(model, 2).dimmed).toBeNull();
    expect(model.baseline?.assetRef).toBe(ref(4));
    expect(model.current?.assetRef).toBe(ref(5));
    expect(pointOf(model, 4).role).toBe("baseline");
    expect(pointOf(model, 5).role).toBe("current");
    expect(model.days).toBe(41);
    expect(model.reversed).toBe(false);
    expect(model.unordered).toEqual([]);
    // 같은 좌표계(5186)만 범주색을 받고, 다른 분석 좌표계는 다른 색 번호다.
    expect(pointOf(model, 2).swatch).toBe(1);
    expect(pointOf(model, 1).swatch).toBe(2);
    expect(pointOf(model, 3).swatch).toBeNull(); // 정사영상은 좌표계를 읽지 않는다.
  });

  it("분석 좌표계 둘과 분석 밖 하나: OK, 분석 밖 하나는 좌표계 다름으로 흐리게", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, ...interval("2026-08-01") }), fact({ n: 2, ...interval("2026-08-10") }), fact({ n: 3, ...interval("2026-08-20") })]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:5186"), catalog(3, "EPSG:3857")],
    });
    expect(model.status).toBe("OK");
    const outside = model.slots.flatMap((slot) => slot.points).find((point) => point.assetRef === ref(3))!;
    expect(outside.swatch).toBeNull();
    expect(outside.dimmed).toBe("crs-different");
    expect(outside.pair).toBeNull();
    expect(pointOf(model, 1).dimmed).toBeNull();
  });

  it("높이 DSM 둘이 같은 분석 밖 좌표계면 OK이고 둘 다 선택할 수 있다(회색, 흐리지 않음)", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, ...interval("2026-08-01") }), fact({ n: 2, ...interval("2026-08-20") })]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:32750"), catalog(2, "EPSG:32750")],
    });
    expect(model.status).toBe("OK");
    expect(model.referenceCrs).toBe("EPSG:32750");
    expect(model.referenceSwatch).toBeNull();
    for (const n of [1, 2]) {
      const point = pointOf(model, n);
      expect(point.dimmed).toBeNull();
      expect(point.swatch).toBeNull();
      expect(point.pair).not.toBeNull();
    }
    expect(pointOf(model, 2).pair).toEqual({ baselineAssetRef: ref(1), currentAssetRef: ref(2) });
  });

  it("분석 밖 좌표계 둘이 서로 다르면 CRS_MISMATCH", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, ...interval("2026-08-01") }), fact({ n: 2, ...interval("2026-08-20") })]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:32750"), catalog(2, "EPSG:3857")],
    });
    expect(model.status).toBe("CRS_MISMATCH");
    // 동률이면 가장 이른 촬영의 좌표계가 기준이다.
    expect(model.referenceCrs).toBe("EPSG:32750");
    expect(pointOf(model, 2).dimmed).toBe("crs-different");
  });

  it("분석 좌표계 하나와 같은 분석 밖 좌표계 둘이면 짝이 되는 분석 밖 쪽을 기준으로 OK", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, ...interval("2026-08-01") }), fact({ n: 2, ...interval("2026-08-10") }), fact({ n: 3, ...interval("2026-08-20") })]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:32750"), catalog(3, "EPSG:32750")],
    });
    expect(model.status).toBe("OK");
    expect(model.referenceCrs).toBe("EPSG:32750");
    expect(pointOf(model, 1).dimmed).toBe("crs-different");
  });

  it("고른 쌍이 있으면 이전 자료의 좌표계가 기준이고, 상태는 쌍과 무관하다", () => {
    const model = build({ baselineAssetRef: ref(1), currentAssetRef: ref(5) });
    expect(model.referenceCrs).toBe("EPSG:32652");
    expect(model.status).toBe("OK");
  });

  it("짝 후보는 띠에 올라온 점으로 한정한다(오래된 점을 고르지 않는다)", () => {
    const dated = Array.from({ length: 10 }, (_, i) =>
      fact({ n: i + 1, ...interval(new Date(Date.UTC(2026, 0, 1 + i * 10)).toISOString().slice(0, 10)) }));
    const model = buildCompareTimeline({
      facts: facts(dated),
      workAreaId: AREA,
      catalogAssets: dated.map((_, i) => catalog(i + 1, "EPSG:5186")),
    });
    expect(model.slots).toHaveLength(8);
    expect(model.hiddenCount).toBe(2);
    // 가장 오래된 올라온 점(3번)은 이전이 되어 바로 뒤와 짝이 된다. 숨은 1·2번과 짝이 되지 않는다.
    expect(pointOf(model, 3).pair).toEqual({ baselineAssetRef: ref(3), currentAssetRef: ref(4) });
  });

  it("해석된 쌍을 요청했는데 점에서 못 찾으면 selectionMissing", () => {
    const missing = build({ baselineAssetRef: ref(3), currentAssetRef: ref(5) }); // 3은 정사영상이라도 순서 점이다
    expect(missing.selectionMissing).toBe(false);
    const tied = buildCompareTimeline({
      facts: facts([fact({ n: 1, chronologyCandidate: false, captureDate: "2026-09-14" }), fact({ n: 2, ...interval("2026-10-02") })]),
      workAreaId: AREA, catalogAssets: [catalog(2, "EPSG:5186")],
      baselineAssetRef: ref(1), currentAssetRef: ref(2),
    });
    expect(tied.selectionMissing).toBe(true);
    expect(tied.baseline).toBeNull();
    expect(build().selectionMissing).toBe(false);
  });

  it("표시 준비 전인 순서 후보는 흐리게 두고 누를 수 없다", () => {
    const model = buildCompareTimeline({
      facts: facts([
        fact({ n: 1, ...interval("2026-08-01") }),
        fact({ n: 2, ...interval("2026-08-10") }),
        fact({ n: 3, ...interval("2026-08-20"), displayReady: false }),
      ]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:5186"), catalog(3, "EPSG:5186")],
    });
    expect(pointOf(model, 3).dimmed).toBe("not-ready");
    expect(pointOf(model, 3).pair).toBeNull();
    expect(model.status).toBe("OK");
  });

  it("ONLY_ONE: 높이 자료가 하나뿐이면 둘 이상 못 고른다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, ...interval("2026-10-02") }), fact({ n: 2, kind: "ortho", ...interval("2026-11-12") })]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:5186", "ortho")],
    });
    expect(model.status).toBe("ONLY_ONE");
    expect(model.heightCount).toBe(1);
    expect(model.hasPickable).toBe(false);
  });

  it("CRS_MISMATCH: 높이 자료가 둘이어도 같은 좌표계가 아니면 비교 후보가 없다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, ...interval("2026-10-02") }), fact({ n: 2, ...interval("2026-11-12") })]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:32652")],
    });
    expect(model.status).toBe("CRS_MISMATCH");
    expect(model.hasPickable).toBe(false);
    const dimmed = model.slots.flatMap((slot) => slot.points).filter((point) => point.dimmed === "crs-different");
    expect(dimmed).toHaveLength(1);
  });

  it("좌표계를 아직 읽지 못한 DSM은 단정하지 않고 고를 수 있게 둔다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, ...interval("2026-10-02") }), fact({ n: 2, ...interval("2026-11-12") })]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186")], // 2는 카탈로그에 없다.
    });
    expect(model.status).toBe("OK");
    expect(pointOf(model, 2).crs).toBeNull();
    expect(pointOf(model, 2).dimmed).toBeNull();
  });

  it("NO_ORDERABLE: 순서 있는 점이 없으면 모두 순서 미정이다(날짜만·미상)", () => {
    const model = buildCompareTimeline({
      facts: facts([
        fact({ n: 1, chronologyCandidate: false, captureDate: "2026-09-14" }),
        fact({ n: 2, chronologyCandidate: false }),
      ]),
      workAreaId: AREA,
      catalogAssets: [],
    });
    expect(model.status).toBe("NO_ORDERABLE");
    expect(model.slots).toEqual([]);
    expect(model.unordered.map((item) => [item.reason, item.date])).toEqual([["date-only", "2026-09-14"], ["unknown", null]]);
  });

  it("서버가 순서 후보라 해도 구간이 아니면(날짜만) 점으로 그리지 않는다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, captureDate: "2026-09-14" }), fact({ n: 2, ...interval("2026-10-02") })]),
      workAreaId: AREA,
      catalogAssets: [],
    });
    expect(model.slots.flatMap((slot) => slot.points)).toHaveLength(1);
    expect(model.unordered).toHaveLength(1);
    expect(model.unordered[0]).toMatchObject({ reason: "date-only", date: "2026-09-14" });
  });

  it("시작만 있는 관측은 날짜로 읽지 않고 미상으로 둔다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact({ n: 1, captureStartedAt: "2026-10-02T01:00:00Z", chronologyCandidate: false })]),
      workAreaId: AREA,
      catalogAssets: [],
    });
    expect(model.unordered[0]).toMatchObject({ reason: "unknown", date: null });
    expect(model.status).toBe("NO_ORDERABLE");
  });

  it("같은 구간의 관측과 서버가 동률이라 알린 관측은 순서 미정으로 뺀다", () => {
    const same = interval("2026-10-02");
    const model = buildCompareTimeline({
      facts: facts([
        fact({ n: 1, ...same }),
        fact({ n: 2, ...same }),
        fact({ n: 3, ...interval("2026-11-12") }),
        fact({ n: 4, ...interval("2026-11-20") }),
      ]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:5186"), catalog(3, "EPSG:5186"), catalog(4, "EPSG:5186")],
      tiedEpochIds: ["epoch-4"],
    });
    expect(model.unordered.map((item) => [item.assetRef, item.reason]).sort()).toEqual([
      [ref(1), "tie"], [ref(2), "tie"], [ref(4), "tie"],
    ]);
    expect(model.slots.flatMap((slot) => slot.points).map((point) => point.assetRef)).toEqual([ref(3)]);
    expect(model.status).toBe("ONLY_ONE");
  });

  it("같은 날짜의 두 관측은 한 칸에 시각순으로 쌓고 시각을 붙인다", () => {
    const model = buildCompareTimeline({
      facts: facts([
        fact({ n: 1, ...interval("2026-10-02", 14) }),
        fact({ n: 2, ...interval("2026-10-02", 9) }),
        fact({ n: 3, ...interval("2026-11-12") }),
      ]),
      workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:5186"), catalog(3, "EPSG:5186")],
      baselineAssetRef: ref(2),
      currentAssetRef: ref(1),
    });
    const slot = model.slots.find((item) => item.date === "2026-10-02")!;
    expect(slot.points.map((point) => [point.assetRef, point.time])).toEqual([[ref(2), "09:00"], [ref(1), "14:00"]]);
    expect(model.days).toBe(0);
    expect(model.slots.find((item) => item.date === "2026-11-12")!.points[0]!.time).toBeNull();
    expect(model.status).toBe("OK");
  });

  it("누르면 이전·이후 쌍이 시간 순서대로 만들어진다", () => {
    const none = build();
    // 쌍이 없을 때: 고른 점이 이후, 바로 앞 점이 이전(앞이 없으면 고른 점이 이전).
    expect(pointOf(none, 4).pair).toEqual({ baselineAssetRef: ref(2), currentAssetRef: ref(4) });
    expect(pointOf(none, 4).becomes).toBe("current");
  });

  it("쌍이 없을 때 가장 앞의 누를 수 있는 점은 이전이 되어 바로 뒤 점과 짝이 된다", () => {
    const model = build();
    // 07-03(좌표계 다름)과 09-11(높이 없음)은 누를 수 없고, 08-21이 가장 앞이다.
    const first = pointOf(model, 2);
    expect(first.pair).toEqual({ baselineAssetRef: ref(2), currentAssetRef: ref(4) });
    expect(first.becomes).toBe("baseline");
    expect(pointOf(model, 1).pair).toBeNull();
    expect(pointOf(model, 3).pair).toBeNull();
  });

  it("쌍이 있을 때: 바깥은 그 쪽 끝을 바꾸고 안쪽은 가까운 쪽을 바꾼다", () => {
    const model = buildCompareTimeline({
      facts: facts([
        fact({ n: 1, ...interval("2026-07-01") }),
        fact({ n: 2, ...interval("2026-08-01") }),
        fact({ n: 3, ...interval("2026-08-10") }),
        fact({ n: 4, ...interval("2026-09-20") }),
        fact({ n: 5, ...interval("2026-10-30") }),
        fact({ n: 6, ...interval("2026-12-01") }),
      ]),
      workAreaId: AREA,
      catalogAssets: [1, 2, 3, 4, 5, 6].map((n) => catalog(n, "EPSG:5186")),
      baselineAssetRef: ref(2),
      currentAssetRef: ref(5),
    });
    const at = (n: number) => model.slots.flatMap((slot) => slot.points).find((point) => point.assetRef === ref(n))!;
    expect(at(1).pair).toEqual({ baselineAssetRef: ref(1), currentAssetRef: ref(5) });
    expect(at(6).pair).toEqual({ baselineAssetRef: ref(2), currentAssetRef: ref(6) });
    expect(at(3).pair).toEqual({ baselineAssetRef: ref(3), currentAssetRef: ref(5) }); // 이전에 가깝다
    expect(at(4).pair).toEqual({ baselineAssetRef: ref(2), currentAssetRef: ref(4) }); // 이후에 가깝다
    expect(at(2).pair).toEqual({ baselineAssetRef: ref(2), currentAssetRef: ref(5) }); // 고른 점은 제자리
    expect(model.days).toBe(retainedDays("2026-08-01", "2026-10-30"));
  });

  it("이전이 이후보다 늦게 온 주소는 reversed로 알리고 쌍은 시간 순서로 되돌려 만든다", () => {
    const model = build({ baselineAssetRef: ref(5), currentAssetRef: ref(4) });
    expect(model.reversed).toBe(true);
    expect(model.days).toBe(41);
    expect(pointOf(model, 5).pair).toEqual({ baselineAssetRef: ref(4), currentAssetRef: ref(5) });
  });

  it("고른 두 점의 좌표계가 다르면 selectionCrsMismatch이고 두 점을 흐리지 않는다", () => {
    const model = build({ baselineAssetRef: ref(1), currentAssetRef: ref(5) });
    expect(model.selectionCrsMismatch).toBe(true);
    expect(pointOf(model, 1).dimmed).toBeNull();
    expect(pointOf(model, 1).role).toBe("baseline");
  });

  it("주소의 참조를 찾을 수 없으면 선택 없음으로 둔다(대신 고르지 않는다)", () => {
    const model = build({ baselineAssetRef: ref(99), currentAssetRef: ref(5) });
    expect(model.baseline).toBeNull();
    expect(model.current).toBeNull();
    expect(model.days).toBeNull();
  });

  it("고른 날짜는 8개를 넘어도 띠에 올리고, 못 올린 수를 알린다", () => {
    const dated = Array.from({ length: 12 }, (_, i) =>
      fact({ n: i + 1, ...interval(new Date(Date.UTC(2026, 0, 1 + i * 10)).toISOString().slice(0, 10)) }));
    const model = buildCompareTimeline({
      facts: facts(dated),
      workAreaId: AREA,
      catalogAssets: dated.map((_, i) => catalog(i + 1, "EPSG:5186")),
      baselineAssetRef: ref(1),
      currentAssetRef: ref(12),
    });
    expect(model.slots).toHaveLength(8);
    expect(model.slots[0]!.points[0]!.assetRef).toBe(ref(1));
    expect(model.slots[model.slots.length - 1]!.points[0]!.assetRef).toBe(ref(12));
    expect(model.hiddenCount).toBe(4);
    expect(model.orderedCount).toBe(12);
  });

  it("좌표계 안내 문구는 분석 좌표계 집합과 같은 범위다", () => {
    expect([...ANALYSIS_CRS].sort()).toEqual(["EPSG:32651", "EPSG:32652", "EPSG:5179", "EPSG:5185", "EPSG:5186", "EPSG:5187", "EPSG:5188"]);
    expect(ANALYSIS_CRS_HINT).toBe("5179 · 5185–5188 · UTM 51N · 52N");
    expect(shortCrs("EPSG:5186")).toBe("5186");
  });
});

function retainedDays(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}
