import { describe, expect, it } from "vitest";

import type { GeoTiffLayout, GeoTiffRawHeader } from "@/lib/geo/geotiff-header";
import { MAX_INSPECTABLE_BYTES, preflightGeoTiff, worstLevel } from "@/lib/geo/geotiff-preflight";

const baseLayout: GeoTiffLayout = {
  compression: 8, predictor: 1, photometric: 1, planarConfiguration: 1, extraSamples: [],
  hasNoDataTag: false, scale: null, offset: null, georeferenced: true,
  modelType: 1, projLinearUnits: null, verticalCsType: 5703, verticalUnits: null,
};

function dsm(overrides: Partial<GeoTiffRawHeader> = {}, layout: Partial<GeoTiffLayout> = {}): GeoTiffRawHeader {
  return {
    width: 100, height: 100, samplesPerPixel: 1, bitsPerSample: 32, sampleFormat: 3,
    geoKeys: { GTModelTypeGeoKey: 1, ProjectedCSTypeGeoKey: 5186 }, software: null, dateTime: null, pixelSize: [0.05, 0.05],
    layout: { ...baseLayout, ...layout }, ...overrides,
  };
}

function ortho(overrides: Partial<GeoTiffRawHeader> = {}, layout: Partial<GeoTiffLayout> = {}): GeoTiffRawHeader {
  return {
    width: 100, height: 100, samplesPerPixel: 3, bitsPerSample: 8, sampleFormat: 1,
    geoKeys: { GTModelTypeGeoKey: 1, ProjectedCSTypeGeoKey: 32652 }, software: null, dateTime: null, pixelSize: [0.03, 0.03],
    layout: { ...baseLayout, photometric: 2, verticalCsType: null, ...layout }, ...overrides,
  };
}

const codes = (findings: ReturnType<typeof preflightGeoTiff>) => findings.map((finding) => finding.code);

describe("preflightGeoTiff — 정상 파일", () => {
  it("수직 기준까지 있는 한국 좌표계 DSM 은 아무 점검도 만들지 않는다", () => {
    expect(preflightGeoTiff("dsm", dsm(), 1_000_000)).toEqual([]);
  });

  it("RGB 정사영상(UTM)은 아무 점검도 만들지 않는다", () => {
    expect(preflightGeoTiff("ortho", ortho(), 1_000_000)).toEqual([]);
  });

  it("헤더에 구조 사실(layout)이 없으면 모르는 것으로 두고 점검하지 않는다", () => {
    const bare = dsm();
    delete bare.layout;
    expect(preflightGeoTiff("dsm", bare, null)).toEqual([]);
  });
});

describe("preflightGeoTiff — DSM", () => {
  it("정수 DEM 은 막는다", () => {
    const findings = preflightGeoTiff("dsm", dsm({ bitsPerSample: 16, sampleFormat: 2 }), null);
    expect(codes(findings)).toContain("DSM_BAND_MODEL");
    expect(findings.find((f) => f.code === "DSM_BAND_MODEL")).toMatchObject({ level: "blocked" });
    expect(findings.find((f) => f.code === "DSM_BAND_MODEL")?.title).toContain("16비트 부호 있는 정수 1밴드");
  });

  it("다중 밴드 DSM 은 막는다", () => {
    expect(codes(preflightGeoTiff("dsm", dsm({ samplesPerPixel: 2 }), null))).toContain("DSM_BAND_MODEL");
  });

  it("위·경도 DSM 은 막고 투영 좌표계로 안내한다", () => {
    const findings = preflightGeoTiff("dsm", dsm({ geoKeys: { GTModelTypeGeoKey: 2, GeographicTypeGeoKey: 4326 } }, { modelType: 2 }), null);
    const hit = findings.find((f) => f.code === "DSM_GEOGRAPHIC");
    expect(hit?.level).toBe("blocked");
    expect(hit?.title).toContain("EPSG:4326");
    expect(hit?.fix).toContain("투영 좌표계");
  });

  it("정사영상은 위·경도 좌표계도 받는다", () => {
    const findings = preflightGeoTiff("ortho", ortho({ geoKeys: { GTModelTypeGeoKey: 2, GeographicTypeGeoKey: 4326 } }, { modelType: 2 }), null);
    expect(codes(findings)).not.toContain("DSM_GEOGRAPHIC");
    expect(findings).toEqual([]);
  });

  it("JPEG·LERC 같은 압축은 막고 압축 이름을 보인다", () => {
    for (const [compression, name] of [[7, "JPEG"], [34887, "LERC"]] as const) {
      const hit = preflightGeoTiff("dsm", dsm({}, { compression }), null).find((f) => f.code === "DSM_COMPRESSION");
      expect(hit?.title).toContain(name);
    }
  });

  it("허용 압축 {무압축, LZW, Deflate, ZSTD} 는 통과한다", () => {
    for (const compression of [1, 5, 8, 32946, 50000]) {
      expect(codes(preflightGeoTiff("dsm", dsm({}, { compression }), null))).not.toContain("DSM_COMPRESSION");
    }
  });

  it("예측 설정은 압축 여부에 따라 달리 본다", () => {
    expect(codes(preflightGeoTiff("dsm", dsm({}, { compression: 1, predictor: 3 }), null))).toContain("DSM_PREDICTOR");
    expect(codes(preflightGeoTiff("dsm", dsm({}, { compression: 8, predictor: 3 }), null))).not.toContain("DSM_PREDICTOR");
    expect(codes(preflightGeoTiff("dsm", dsm({}, { compression: 8, predictor: 2 }), null))).toContain("DSM_PREDICTOR");
  });

  it("색 방식이 MinIsBlack 이 아니거나 없으면 막는다", () => {
    expect(codes(preflightGeoTiff("dsm", dsm({}, { photometric: 2 }), null))).toContain("DSM_PHOTOMETRIC");
    expect(codes(preflightGeoTiff("dsm", dsm({}, { photometric: null }), null))).toContain("DSM_PHOTOMETRIC");
  });

  it("배율·보정이 있으면 막고, 1·0 은 통과한다", () => {
    expect(codes(preflightGeoTiff("dsm", dsm({}, { scale: 0.01 }), null))).toContain("DSM_SCALE_OFFSET");
    expect(codes(preflightGeoTiff("dsm", dsm({}, { offset: 100 }), null))).toContain("DSM_SCALE_OFFSET");
    expect(codes(preflightGeoTiff("dsm", dsm({}, { scale: 1, offset: 0 }), null))).not.toContain("DSM_SCALE_OFFSET");
  });

  it("NoData 값 지정은 DSM 에서는 문제가 아니다", () => {
    expect(codes(preflightGeoTiff("dsm", dsm({}, { hasNoDataTag: true }), null))).toEqual([]);
  });

  it("수직 기준이 없으면 알려 준다(막지는 않는다)", () => {
    const findings = preflightGeoTiff("dsm", dsm({}, { verticalCsType: null }), null);
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({ code: "NO_VERTICAL_REFERENCE", level: "notice" });
    // 선언으로 높이·단면을 읽을 수 있고, 체적·비교는 안 된다는 점을 함께 말한다.
    expect(findings[0].title).toContain("수직 기준을 선언하면 높이·단면을 읽을 수 있습니다");
    expect(findings[0].title).toContain("체적·두 시점 비교에는 쓸 수 없습니다");
    expect(findings[0].title).not.toContain("높이·단면·체적 분석에 쓸 수 없습니다");
  });

  it("정사영상에는 수직 기준 안내를 하지 않는다", () => {
    expect(codes(preflightGeoTiff("ortho", ortho({}, { verticalCsType: null }), null))).not.toContain("NO_VERTICAL_REFERENCE");
  });

  it("수직 기준이 사용자 정의이거나 미터가 아니면 거부될 수 있다고 알린다", () => {
    expect(preflightGeoTiff("dsm", dsm({}, { verticalCsType: 32767 }), null).find((f) => f.code === "VERTICAL_USER_DEFINED")?.level).toBe("may");
    expect(preflightGeoTiff("dsm", dsm({}, { verticalUnits: 9002 }), null).find((f) => f.code === "VERTICAL_UNIT_NOT_METRE")?.level).toBe("may");
    expect(codes(preflightGeoTiff("dsm", dsm({}, { verticalUnits: 9001 }), null))).toEqual([]);
  });

  it("한국 좌표계가 아닌 투영 DSM 은 분석 제한만 알린다", () => {
    const findings = preflightGeoTiff("dsm", dsm({ geoKeys: { GTModelTypeGeoKey: 1, ProjectedCSTypeGeoKey: 7850 } }), null);
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({ code: "CRS_NOT_ANALYSIS", level: "notice" });
    expect(findings[0].title).toContain("EPSG:7850");
  });

  it("좌표 단위가 미터가 아닌 투영 DSM 은 거부될 수 있다고 알린다", () => {
    expect(preflightGeoTiff("dsm", dsm({}, { projLinearUnits: 9002 }), null).find((f) => f.code === "DSM_UNIT_NOT_METRE")?.level).toBe("may");
  });
});

describe("preflightGeoTiff — 정사영상", () => {
  it("16비트와 5밴드 이상을 막는다", () => {
    expect(codes(preflightGeoTiff("ortho", ortho({ bitsPerSample: 16 }), null))).toContain("ORTHO_BAND_MODEL");
    expect(codes(preflightGeoTiff("ortho", ortho({ samplesPerPixel: 5 }), null))).toEqual(expect.arrayContaining(["TOO_MANY_BANDS"]));
  });

  it("단일 실수 밴드(DSM)를 정사영상 칸에 넣으면 막는다", () => {
    expect(codes(preflightGeoTiff("ortho", dsm(), null))).toContain("ORTHO_BAND_MODEL");
  });

  it("NoData 값이 지정되면 막는다", () => {
    expect(preflightGeoTiff("ortho", ortho({}, { hasNoDataTag: true }), null).find((f) => f.code === "ORTHO_NODATA")?.level).toBe("blocked");
  });

  it("알파가 있는 JPEG 는 막고, 알파 없는 YCbCr JPEG 는 통과한다", () => {
    const rgba = preflightGeoTiff("ortho", ortho({ samplesPerPixel: 4 }, { compression: 7, photometric: 6 }), null);
    expect(codes(rgba)).toContain("ORTHO_JPEG");
    expect(codes(preflightGeoTiff("ortho", ortho({}, { compression: 7, photometric: 6 }), null))).toEqual([]);
    expect(codes(preflightGeoTiff("ortho", ortho({}, { compression: 7, photometric: 2 }), null))).toContain("ORTHO_JPEG");
  });

  it("JPEG 2000 등 허용 밖 압축은 막는다", () => {
    expect(preflightGeoTiff("ortho", ortho({}, { compression: 34712 }), null).find((f) => f.code === "ORTHO_COMPRESSION")?.title).toContain("JPEG 2000");
  });

  it("RGB 가 아닌 색 방식은 막는다", () => {
    expect(codes(preflightGeoTiff("ortho", ortho({}, { photometric: 1 }), null))).toContain("ORTHO_PHOTOMETRIC");
  });

  it("예측 설정은 JPEG·무압축에서는 1 만 받는다", () => {
    expect(codes(preflightGeoTiff("ortho", ortho({}, { compression: 8, predictor: 2 }), null))).toEqual([]);
    expect(codes(preflightGeoTiff("ortho", ortho({}, { compression: 1, predictor: 2 }), null))).toContain("ORTHO_PREDICTOR");
    expect(codes(preflightGeoTiff("ortho", ortho({}, { compression: 8, predictor: 3 }), null))).toContain("ORTHO_PREDICTOR");
  });

  it("RGBA 는 알파가 이진이어야 한다는 점만 참고로 알린다(대부분의 정상 RGBA 를 겁주지 않는다)", () => {
    const findings = preflightGeoTiff("ortho", ortho({ samplesPerPixel: 4 }, { extraSamples: [2] }), null);
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({ code: "ORTHO_ALPHA_BINARY", level: "notice" });
  });

  it("네 번째 밴드가 알파로 표시되지 않으면 추가로 알린다", () => {
    const findings = preflightGeoTiff("ortho", ortho({ samplesPerPixel: 4 }, { extraSamples: [0] }), null);
    expect(codes(findings)).toEqual(expect.arrayContaining(["ORTHO_ALPHA_BINARY", "ORTHO_ALPHA_UNSPECIFIED"]));
  });
});

describe("preflightGeoTiff — 공통", () => {
  it("위치 정보가 없으면 막는다", () => {
    expect(codes(preflightGeoTiff("dsm", dsm({ geoKeys: null }, { georeferenced: false }), null))).toEqual(["NO_GEOREFERENCE"]);
    expect(codes(preflightGeoTiff("ortho", ortho({}, { georeferenced: false }), null))).toContain("NO_GEOREFERENCE");
  });

  it("EPSG 번호가 없는 사용자 정의 좌표계는 막지 않고 확인 필요로 알린다", () => {
    const findings = preflightGeoTiff("ortho", ortho({ geoKeys: { GTModelTypeGeoKey: 1, ProjectedCSTypeGeoKey: 32767 } }), null);
    expect(findings.map((f) => [f.code, f.level])).toEqual([["NO_EPSG", "may"]]);
  });

  it("실제 공개 DSM 의 사용자 정의 좌표계(GDA94 / MGA zone 50)는 거부 예상으로 말하지 않는다", () => {
    // floreat4_all_10cm-dsm.tif 의 GeoKey. 실제 검사 스택은 이를 EPSG:28350 으로 확인한다.
    const geoKeys = { GTModelTypeGeoKey: 1, GTRasterTypeGeoKey: 1, GTCitationGeoKey: "GDA_1994_MGA_Zone_50", GeographicTypeGeoKey: 32767, ProjectedCSTypeGeoKey: 32767, ProjectionGeoKey: 16150, ProjLinearUnitsGeoKey: 9001 };
    const findings = preflightGeoTiff("dsm", dsm({ geoKeys }, { verticalCsType: null, projLinearUnits: 9001 }), 29_693_002);
    expect(findings.map((f) => f.level)).not.toContain("blocked");
    expect(codes(findings)).toContain("NO_EPSG");
  });

  it("실제 공개 DSM(Pix4D 내보내기, EPSG:7850, Float32, NoData)은 참고 두 가지만 남긴다", () => {
    const findings = preflightGeoTiff("dsm", dsm({ geoKeys: { GTModelTypeGeoKey: 1, ProjectedCSTypeGeoKey: 7850, ProjLinearUnitsGeoKey: 9001 }, software: "pix4dmapper" }, { compression: 1, hasNoDataTag: true, verticalCsType: null, projLinearUnits: 9001 }), 181_144_647);
    expect(findings.map((f) => [f.code, f.level]).sort()).toEqual([["CRS_NOT_ANALYSIS", "notice"], ["NO_VERTICAL_REFERENCE", "notice"]]);
  });

  it("지심 좌표계는 막는다", () => {
    expect(codes(preflightGeoTiff("ortho", ortho({}, { modelType: 3 }), null))).toContain("GEOCENTRIC_CRS");
  });

  it("밴드가 분리 저장된 다중 밴드 파일은 막는다", () => {
    expect(codes(preflightGeoTiff("ortho", ortho({}, { planarConfiguration: 2 }), null))).toContain("PLANAR_SEPARATE");
    expect(codes(preflightGeoTiff("dsm", dsm({}, { planarConfiguration: 2 }), null))).not.toContain("PLANAR_SEPARATE");
  });

  it("검사 상한 2 GiB 를 넘는 파일만 막는다", () => {
    expect(codes(preflightGeoTiff("dsm", dsm(), MAX_INSPECTABLE_BYTES))).toEqual([]);
    expect(preflightGeoTiff("dsm", dsm(), MAX_INSPECTABLE_BYTES + 1).find((f) => f.code === "FILE_TOO_LARGE")?.level).toBe("blocked");
  });

  it("가장 심각한 수준을 돌려준다", () => {
    expect(worstLevel([])).toBeNull();
    const findings = preflightGeoTiff("dsm", dsm({ bitsPerSample: 16, sampleFormat: 2 }, { verticalCsType: null }), null);
    expect(worstLevel(findings)).toBe("blocked");
    expect(worstLevel(findings.filter((f) => f.level === "notice"))).toBe("notice");
  });

  it("모든 점검은 무엇을 고칠지(고칠 수 없는 경우 제외) 문장으로 안내한다", () => {
    const worst = [
      preflightGeoTiff("dsm", dsm({ bitsPerSample: 16, sampleFormat: 2, geoKeys: null }, { georeferenced: false, compression: 7 }), 3 * 2 ** 30),
      preflightGeoTiff("ortho", ortho({ samplesPerPixel: 4 }, { hasNoDataTag: true, compression: 34712 }), null),
    ].flat();
    expect(worst.length).toBeGreaterThan(4);
    for (const finding of worst) {
      expect(finding.title.length).toBeGreaterThan(5);
      expect(finding.fix === null || finding.fix.length > 5).toBe(true);
    }
  });
});
