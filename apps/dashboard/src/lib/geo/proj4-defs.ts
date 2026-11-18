import proj4 from "proj4";

import { KOREA_2000_TM_DEFS } from "./known-crs";

/**
 * `known-crs.ts` 의 표시용 투영좌표계를 proj4에 등록한다. WGS84 UTM은 proj4가 이름으로
 * 알지 못하므로 존마다 정의를 만들어 넣는다.
 */

let registered = false;

/** 멱등이다 — 여러 지도 컴포넌트가 마운트될 때마다 다시 등록해도 안전하다. */
export function registerKnownProjections(): void {
  if (registered) return;
  for (const [code, def] of Object.entries(KOREA_2000_TM_DEFS)) {
    proj4.defs(code, def);
  }
  for (const south of [false, true]) {
    for (let zone = 1; zone <= 60; zone += 1) {
      const code = `EPSG:32${south ? 7 : 6}${String(zone).padStart(2, "0")}`;
      proj4.defs(code, `+proj=utm +zone=${zone}${south ? " +south" : ""} +datum=WGS84 +units=m +no_defs`);
    }
  }
  registered = true;
}

export { proj4 };
