import { describe, expect, it } from "vitest";

import { assignCandidates, chipsOf, inspectCandidate, type UploadCandidate } from "@/lib/site-upload-files";
import type { GeoTiffRawHeader } from "@/lib/geo/geotiff-header";

const layout = {
  compression: 8, predictor: 1, photometric: 1, planarConfiguration: 1, extraSamples: [], hasNoDataTag: true, scale: null, offset: null,
  georeferenced: true, modelType: 1, projLinearUnits: 9001, verticalCsType: null, verticalUnits: null,
};
const dsmHeader: GeoTiffRawHeader = {
  width: 100, height: 100, samplesPerPixel: 1, bitsPerSample: 32, sampleFormat: 3,
  geoKeys: { ProjectedCSTypeGeoKey: 5186 }, software: null, dateTime: null, pixelSize: [0.1, 0.1],
  boundingBox: [200000, 550000, 201000, 551000], layout,
};
const orthoHeader: GeoTiffRawHeader = { ...dsmHeader, samplesPerPixel: 3, bitsPerSample: 8, sampleFormat: 1, layout: { ...layout, photometric: 2 } };

function f(name: string, size = 1000): File {
  return Object.defineProperty(new File([new Uint8Array(1)], name), "size", { value: size }) as File;
}

function around(lon: number, lat: number, half: number): Record<string, unknown> {
  return { type: "Polygon", coordinates: [[[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half], [lon - half, lat + half], [lon - half, lat - half]]] };
}

describe("inspectCandidate", () => {
  it("recognizes a DSM from the header and computes footprint, coverage and findings", async () => {
    const probe = await inspectCandidate(f("a.tif"), "1", null, { read: async () => dsmHeader });
    const center = probe.footprint!.ring.reduce((acc, [lon, lat]) => [acc[0]! + lon / 4, acc[1]! + lat / 4], [0, 0]);
    const candidate = await inspectCandidate(f("dsm.tif"), "2", around(center[0]!, center[1]!, 0.0005), { read: async () => dsmHeader });
    expect(candidate).toMatchObject({ readable: true, kind: "dsm", coverage: "covers" });
    expect(candidate.findings.map((item) => item.code)).toContain("NO_VERTICAL_REFERENCE");
  });

  it("does not guess the kind from the file name when the header is ambiguous", async () => {
    const ambiguous: GeoTiffRawHeader = { ...dsmHeader, samplesPerPixel: 1, bitsPerSample: 8, sampleFormat: 1 };
    const candidate = await inspectCandidate(f("final_dsm.tif"), "6", null, { read: async () => ambiguous });
    expect(candidate).toMatchObject({ readable: true, kind: null, findings: [] });
  });

  it("marks unreadable files without guessing a kind", async () => {
    const candidate = await inspectCandidate(f("x.tif"), "3", null, { read: async () => { throw new Error("not tiff"); } });
    expect(candidate).toMatchObject({ readable: false, kind: null, header: null, footprint: null, coverage: null });
    expect(candidate.findings).toEqual([]);
  });

  it("rethrows aborts instead of reporting an unreadable file", async () => {
    await expect(inspectCandidate(f("x.tif"), "4", null, { read: async () => { throw new DOMException("aborted", "AbortError"); } })).rejects.toMatchObject({ name: "AbortError" });
  });

  it("leaves coverage null when the area shape is unreadable", async () => {
    const candidate = await inspectCandidate(f("dsm.tif"), "5", { coordinates: "broken" }, { read: async () => dsmHeader });
    expect(candidate.footprint).not.toBeNull();
    expect(candidate.coverage).toBeNull();
  });
});

describe("assignCandidates", () => {
  it("puts files into the slots the headers point at and reports the rest", async () => {
    const list: UploadCandidate[] = [
      await inspectCandidate(f("a.tif"), "1", null, { read: async () => orthoHeader }),
      await inspectCandidate(f("b.tif"), "2", null, { read: async () => dsmHeader }),
      await inspectCandidate(f("c.jpg"), "3", null, { read: async () => { throw new Error("no"); } }),
      await inspectCandidate(f("d.tif"), "4", null, { read: async () => dsmHeader }),
    ];
    const assignment = assignCandidates(list);
    expect(assignment.ortho?.id).toBe("1");
    expect(assignment.dsm?.id).toBe("2");
    expect(assignment.skipped.map((item) => item.id)).toEqual(["3", "4"]);
  });
});

describe("chipsOf", () => {
  const base = async (overrides: Partial<GeoTiffRawHeader> = {}, size = 1000, area: Record<string, unknown> | null = null) =>
    inspectCandidate(f("x.tif", size), "1", area, { read: async () => ({ ...dsmHeader, ...overrides }) });

  it("calls a missing vertical reference out as its own chip and never as a rejection", async () => {
    const chips = chipsOf(await base());
    expect(chips.find((chip) => chip.key === "vertical")).toMatchObject({ tone: "warn", label: "높이 기준 없음" });
    expect(chips.some((chip) => chip.tone === "block")).toBe(false);
  });

  it("shows why a geographic DSM needs a projected export even when its footprint is available", async () => {
    const chips = chipsOf(await base({ geoKeys: { GeographicTypeGeoKey: 4326 }, boundingBox: [23.53, 42.65, 23.54, 42.66] }));
    expect(chips.find((chip) => chip.key === "crs")).toMatchObject({ tone: "block", label: "EPSG:4326 · 투영 좌표계 필요", detail: expect.stringContaining("UTM") });
  });

  it("separates certain rejections from conditions that may be rejected", async () => {
    const tooBig = chipsOf(await base({}, 2 ** 31 + 1));
    expect(tooBig.find((chip) => chip.key === "blocked")).toMatchObject({ tone: "block", label: "거부 예상 1" });
    const userDefined = chipsOf(await base({ layout: { ...layout, verticalCsType: 32767 } }));
    expect(userDefined.find((chip) => chip.key === "may")).toMatchObject({ tone: "warn" });
    expect(userDefined.some((chip) => chip.key === "preflight")).toBe(false);
  });

  it("says nothing is expected to be rejected only when nothing was found", async () => {
    const clean = chipsOf(await base({ layout: { ...layout, verticalCsType: 5173, verticalUnits: 9001 } }));
    expect(clean.find((chip) => chip.key === "preflight")).toMatchObject({ tone: "ok", label: "거부 예상 없음" });
    const unreadable = chipsOf(await inspectCandidate(f("x.tif"), "9", null, { read: async () => { throw new Error("x"); } }));
    expect(unreadable).toEqual([]);
  });

  it("describes how the area and file relate", async () => {
    const probe = await base();
    const [lon, lat] = probe.footprint!.ring[0]!;
    const far = chipsOf(await base({}, 1000, around(lon + 2, lat + 2, 0.001)));
    expect(far.find((chip) => chip.key === "coverage")).toMatchObject({ tone: "warn", label: "구역과 안 겹침" });
  });
});
