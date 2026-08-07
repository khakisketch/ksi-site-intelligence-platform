import proj4 from "proj4";

/**
 * `georaster-layer-for-leaflet` 는 EPSG 코드가 `proj4.defs` 에 등록돼 있어야
 * (UTM 계열 제외) 재투영한다 — 없으면 그리기를 포기하고 예외를 던진다. 여기서
 * `packages/geo-spatial` 이 허용하는 다섯 좌표계(EPSG:5185~5188·5179)를
 * 등록한다. 정의 문자열은 국토지리정보원 고시값(epsg.io 공개값과 동일)이고,
 * `ksi_geo_spatial.crs.SUPPORTED_PROJECT_CRS` 의 대응값이다 — 그 목록이
 * 바뀌면 여기도 함께 바뀌어야 한다.
 *
 * pacifica 같은 UTM 계열(EPSG:326xx)은 라이브러리가 자체 UTM 인식으로
 * 처리하므로 여기 등록하지 않는다.
 */
const KOREA_2000_TM_DEFS: Record<string, string> = {
  "EPSG:5185": "+proj=tmerc +lat_0=38 +lon_0=125 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs",
  "EPSG:5186": "+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs",
  "EPSG:5187": "+proj=tmerc +lat_0=38 +lon_0=129 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs",
  "EPSG:5188": "+proj=tmerc +lat_0=38 +lon_0=131 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs",
  "EPSG:5179": "+proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996 +x_0=1000000 +y_0=2000000 +ellps=GRS80 +units=m +no_defs",
};

let registered = false;

/** 멱등이다 — 여러 지도 컴포넌트가 마운트될 때마다 다시 등록해도 안전하다. */
export function registerKoreaProjections(): void {
  if (registered) return;
  for (const [code, def] of Object.entries(KOREA_2000_TM_DEFS)) {
    proj4.defs(code, def);
  }
  registered = true;
}

export { proj4 };
