import { describe, expect, it } from "vitest";

import { isKnownProjectedCrs, wgs84UtmZoneOf } from "@/lib/geo/known-crs";

describe("known display CRS", () => {
  it("reads WGS84 UTM zone and hemisphere from the EPSG code", () => {
    expect(wgs84UtmZoneOf("EPSG:32652")).toEqual({ zone: 52, south: false });
    expect(wgs84UtmZoneOf(" epsg:32651 ")).toEqual({ zone: 51, south: false });
    expect(wgs84UtmZoneOf("EPSG:32750")).toEqual({ zone: 50, south: true });
    expect(wgs84UtmZoneOf("EPSG:32601")).toEqual({ zone: 1, south: false });
    expect(wgs84UtmZoneOf("EPSG:32760")).toEqual({ zone: 60, south: true });
  });

  it("does not mistake neighbouring codes for UTM", () => {
    for (const code of ["EPSG:32600", "EPSG:32661", "EPSG:32700", "EPSG:32767", "EPSG:3265", "EPSG:326520", "EPSG:5186"]) {
      expect(wgs84UtmZoneOf(code)).toBeNull();
    }
  });

  it("knows the five Korean KGD2002 systems and WGS84 UTM, but not Bessel-era Korean systems", () => {
    for (const code of ["EPSG:5179", "EPSG:5185", "EPSG:5186", "EPSG:5187", "EPSG:5188", "EPSG:32652"]) {
      expect(isKnownProjectedCrs(code)).toBe(true);
    }
    for (const code of ["EPSG:5173", "EPSG:5174", "EPSG:5177", "EPSG:5181", "EPSG:3857", "EPSG:4326", ""]) {
      expect(isKnownProjectedCrs(code)).toBe(false);
    }
  });
});
