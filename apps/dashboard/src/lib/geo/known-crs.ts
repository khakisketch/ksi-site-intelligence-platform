/**
 * 화면 표시가 아는 투영좌표계 집합. proj4를 끌어오지 않는 순수 판정이라 현장 목록 타일처럼
 * 가벼운 모듈도 쓸 수 있다. 실제 등록은 `proj4-defs.ts` 의 `registerKnownProjections` 가 한다.
 *
 * 표시 전용이며, 분석이 받는 좌표계 집합(`ksi_geo_spatial.crs.SUPPORTED_PROJECT_CRS`)과는
 * 별개다 — 여기 있다고 체적·단면·비교에 쓸 수 있는 것은 아니다.
 *
 * - 한국 KGD2002(GRS80) 평면직각좌표계 다섯(EPSG:5185~5188·5179). 정의 문자열은
 *   국토지리정보원 고시값(epsg.io 공개값과 동일)이다.
 * - WGS84 UTM 북반구(EPSG:32601~32660)·남반구(EPSG:32701~32760). Pix4D·DJI Terra가
 *   출력 좌표계를 따로 정하지 않으면 촬영 위치의 UTM 존으로 내보낸다(한국은 51N·52N).
 *   UTM 좌표는 북쪽 값이 수백만 m라 한국 평면직각좌표(수십만 m)와 숫자만으로도 구별된다.
 *
 * 구 측지계(Bessel, EPSG:5173~5177)는 넣지 않는다 — 현행 좌표계와 같은 지점에서 수백 m
 * 어긋나는데 숫자로는 구별되지 않아, 그려 주면 틀린 위치를 맞는 것처럼 보이게 한다.
 */
export const KOREA_2000_TM_DEFS: Record<string, string> = {
  "EPSG:5185": "+proj=tmerc +lat_0=38 +lon_0=125 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs",
  "EPSG:5186": "+proj=tmerc +lat_0=38 +lon_0=127 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs",
  "EPSG:5187": "+proj=tmerc +lat_0=38 +lon_0=129 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs",
  "EPSG:5188": "+proj=tmerc +lat_0=38 +lon_0=131 +k=1 +x_0=200000 +y_0=600000 +ellps=GRS80 +units=m +no_defs",
  "EPSG:5179": "+proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996 +x_0=1000000 +y_0=2000000 +ellps=GRS80 +units=m +no_defs",
};

/** `EPSG:326zz`(북)·`EPSG:327zz`(남)의 존과 반구. WGS84 UTM이 아니면 null. */
export function wgs84UtmZoneOf(crs: string): { zone: number; south: boolean } | null {
  const match = /^EPSG:32([67])(\d{2})$/.exec(crs.trim().toUpperCase());
  if (!match) return null;
  const zone = Number(match[2]);
  if (zone < 1 || zone > 60) return null;
  return { zone, south: match[1] === "7" };
}

/** 표시용으로 아는 투영좌표계인가(한국 다섯 + WGS84 UTM). 입력은 `EPSG:n` 표기다. */
export function isKnownProjectedCrs(crs: string): boolean {
  const code = crs.trim().toUpperCase();
  return code in KOREA_2000_TM_DEFS || wgs84UtmZoneOf(code) !== null;
}

/**
 * 분석(높이·단면·체적)이 받는 투영좌표계 — `ksi_geo_spatial.crs.SUPPORTED_PROJECT_CRS` 의 대응값이다.
 * 한국 다섯에 한국을 덮는 UTM 두 존(51N·52N)만 더한다. 다른 대륙의 UTM 존은 지도에는 그리지만
 * 분석에는 받지 않는다 — 현장과 다른 위치로 태깅된 자료가 "같은 좌표계"라는 이유로 비교된 실패가 있었다.
 */
export const ANALYSIS_CRS: ReadonlySet<string> = new Set([...Object.keys(KOREA_2000_TM_DEFS), "EPSG:32651", "EPSG:32652"]);

export function isAnalysisCrs(crs: string): boolean {
  return ANALYSIS_CRS.has(crs.trim().toUpperCase());
}
