/**
 * KSI Platform ksi-safety zone-intrusion.ts 골든 벡터 캡처 (P0-3).
 *
 * 원 구현(참고, 읽기전용):
 *   references/repos/ksi-platform/ksi-safety/src/lib/zone-intrusion.ts
 *   @030ebd5a (ksi-platform HEAD, verify_reference_pins.sh 대상)
 *
 * 이 스크립트는 zone-intrusion.ts 의 순수 헬퍼(enuToLatLng/pointInGpsPolygon/…)와
 * 진입점 evaluateZoneIntrusion() 을 **실제로 실행**해 입력→출력을 캡처한다(손 전사 금지,
 * 대표자 반영사항 8). 출력은
 * packages/test-vectors/vectors/legacy_compat/zone_intrusion.json 에 쓴다.
 *
 * INSIDE/OUTSIDE/NEAR_BOUNDARY/UNKNOWN 매핑 (이 파일엔 Scout ZoneDecision 같은 명시적
 * enum이 없다 — evaluateZoneIntrusion 은 IntrusionEvent[] 만 반환한다):
 *   INSIDE        → 이벤트 반환, inBuffer 없음 (폴리곤/원 내부).
 *   OUTSIDE       → 빈 배열 (투영은 신뢰 가능하나 구역 밖).
 *   NEAR_BOUNDARY → 이벤트 반환, inBuffer=true (경계 밖 bufferM 이내).
 *   UNKNOWN       → 빈 배열이지만 원인이 다르다: 투영 자체를 못 믿어(짐벌 수평/텔레메트리
 *                   시각어긋남) GPS 구역을 평가할 수 없는 경우 — "구역 밖"이 아니라
 *                   "알 수 없음"인데, 안전 정직성 정책상 2D 대체 없이 침묵한다(파일 상단
 *                   주석 참고). OUTSIDE 와 출력이 같아 보여도 입력 조건(투영 신뢰 여부)이
 *                   본질적으로 다르므로 별도 시나리오로 캡처해 둔다.
 *
 * 실행 방법(재추출):
 *   cd tools/vector-extraction
 *   npx -y tsx --tsconfig ../../references/repos/ksi-platform/ksi-safety/tsconfig.json \
 *     capture_platform_zone.mts
 *   (--tsconfig 는 참고 레포 자체의 tsconfig.json(@/* → ./src/*)을 읽기만 한다 — references/
 *    수정 없음. zone-intrusion.ts → proximity-distance.ts → proximity.ts → safety-zone.ts
 *    체인은 순수 TS/JS 로 외부 npm 런타임 의존이 없어 tsx 단독 실행된다.)
 *
 * 이 스크립트는 tools/vector-extraction/ 아래에 있어 scripts/check_no_reference_imports.sh
 * 가드(CODE_DIRS=apps/services/edge/workers/packages/tests) 대상이 아니다 — tools/ 는
 * 가드 제외 디렉토리로, references/ 를 직접 import 해도 되는 유일한 위치다(README.md 참고).
 */

import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { DEFAULT_PROXIMITY_CONFIG } from "../../references/repos/ksi-platform/ksi-safety/src/lib/proximity-distance.ts";
import {
  distanceToGpsPolygonM,
  distanceToGpsZoneM,
  enuToLatLng,
  evaluateZoneIntrusion,
  gpsDistanceM,
  materializeCircleGpsPolygon,
  pointInGpsPolygon,
  pointInPixelPolygon,
  projectFootToGps,
  scalePixelPolygonToFrame,
  zoneCircle,
  type DangerZone,
  type GpsPoint,
} from "../../references/repos/ksi-platform/ksi-safety/src/lib/zone-intrusion.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..", "..");
const OUT_PATH = resolve(
  REPO_ROOT,
  "packages/test-vectors/vectors/legacy_compat/zone_intrusion.json",
);

const cfg = DEFAULT_PROXIMITY_CONFIG;

type Detection = { class?: string; bbox_xyxy?: number[] };

const NADIR_POSE = {
  altitudeM: 30, pitchDeg: -90, yawDeg: 0, rollDeg: 0, hfovDeg: 70,
  imgW: 1920, imgH: 1080, lat: 37.5, lng: 127.0,
};
const PERSON: Detection = { class: "person", bbox_xyxy: [950, 500, 970, 560] };

const SQUARE_POLY: GpsPoint[] = [
  { latitude: 37.499, longitude: 126.999 },
  { latitude: 37.499, longitude: 127.001 },
  { latitude: 37.501, longitude: 127.001 },
  { latitude: 37.501, longitude: 126.999 },
];

type CaseRecord = { id: string; api: string; description: string; input: unknown; output: unknown };
const cases: CaseRecord[] = [];
function pushCase(rec: CaseRecord): void {
  cases.push(rec);
}

// ── 순수 지오메트리 헬퍼 ─────────────────────────────────────────────────────
pushCase({
  id: "enu_to_latlng_basic",
  api: "enuToLatLng",
  description: "원점(37.5,127.0)에서 동10m·북20m 오프셋 → 절대 위경도로 변환.",
  input: { originLat: 37.5, originLng: 127.0, eastM: 10, northM: 20 },
  output: enuToLatLng(37.5, 127.0, 10, 20),
});
pushCase({
  id: "point_in_gps_polygon_inside",
  api: "pointInGpsPolygon",
  description: "정사각 폴리곤(37.499~37.501, 126.999~127.001) 중심점 → 내부(true).",
  input: { point: { latitude: 37.5, longitude: 127.0 }, polygon: SQUARE_POLY },
  output: pointInGpsPolygon({ latitude: 37.5, longitude: 127.0 }, SQUARE_POLY),
});
pushCase({
  id: "point_in_gps_polygon_outside",
  api: "pointInGpsPolygon",
  description: "같은 폴리곤 밖의 점(37.6,127.0) → 외부(false).",
  input: { point: { latitude: 37.6, longitude: 127.0 }, polygon: SQUARE_POLY },
  output: pointInGpsPolygon({ latitude: 37.6, longitude: 127.0 }, SQUARE_POLY),
});
pushCase({
  id: "distance_to_gps_polygon_inside_is_zero",
  api: "distanceToGpsPolygonM",
  description: "폴리곤 내부점 → 경계거리 0(내부는 항상 0).",
  input: { point: { latitude: 37.5, longitude: 127.0 }, polygon: SQUARE_POLY },
  output: distanceToGpsPolygonM({ latitude: 37.5, longitude: 127.0 }, SQUARE_POLY),
});
pushCase({
  id: "distance_to_gps_polygon_outside_nonzero",
  api: "distanceToGpsPolygonM",
  description: "북쪽 경계(37.501)에서 0.009도 더 북쪽(37.51) → 약 1002m.",
  input: { point: { latitude: 37.51, longitude: 127.0 }, polygon: SQUARE_POLY },
  output: distanceToGpsPolygonM({ latitude: 37.51, longitude: 127.0 }, SQUARE_POLY),
});
pushCase({
  id: "gps_distance_m_basic",
  api: "gpsDistanceM",
  description: "위도 0.001도 차이(같은 경도) → 약 111.3m(등장방형 근사).",
  input: { a: { latitude: 37.5, longitude: 127.0 }, b: { latitude: 37.501, longitude: 127.0 } },
  output: gpsDistanceM({ latitude: 37.5, longitude: 127.0 }, { latitude: 37.501, longitude: 127.0 }),
});
pushCase({
  id: "materialize_circle_gps_polygon_octagon",
  api: "materializeCircleGpsPolygon",
  description: "중심(37.5,127.0) 반경20m를 8각형으로 materialize(원형 구역의 폴리곤 근사 렌더용).",
  input: { center: { latitude: 37.5, longitude: 127.0 }, radiusM: 20, segments: 8 },
  output: materializeCircleGpsPolygon({ latitude: 37.5, longitude: 127.0 }, 20, 8),
});
pushCase({
  id: "zone_circle_valid_shape",
  api: "zoneCircle",
  description: "projectionMeta.shape='circle' + center/radiusM 유효 → {center,radiusM} 반환.",
  input: {
    zone: {
      id: "circ_valid",
      gpsPolygon: [],
      projectionMeta: { shape: "circle", center: { latitude: 37.5, longitude: 127.0 }, radiusM: 20 },
    } as DangerZone,
  },
  output: zoneCircle({
    id: "circ_valid", gpsPolygon: [],
    projectionMeta: { shape: "circle", center: { latitude: 37.5, longitude: 127.0 }, radiusM: 20 },
  }),
});
pushCase({
  id: "zone_circle_invalid_missing_center_falls_back_to_polygon",
  api: "zoneCircle",
  description: "shape='circle' 이지만 center 결손(런타임 JSONB 왕복 방어) → null(폴리곤 판정 폴백).",
  input: {
    zone: {
      id: "circ_invalid", gpsPolygon: SQUARE_POLY, projectionMeta: { shape: "circle", radiusM: 20 },
    } as DangerZone,
  },
  output: zoneCircle({
    id: "circ_invalid", gpsPolygon: SQUARE_POLY, projectionMeta: { shape: "circle", radiusM: 20 },
  }),
});
pushCase({
  id: "distance_to_gps_zone_m_circle_inside_is_zero",
  api: "distanceToGpsZoneM",
  description: "원형 구역 중심점 → 정확한 원 거리 경로로 0(내부).",
  input: {
    point: { latitude: 37.5, longitude: 127.0 },
    zone: {
      id: "circ1", gpsPolygon: [],
      projectionMeta: { shape: "circle", center: { latitude: 37.5, longitude: 127.0 }, radiusM: 20 },
    } as DangerZone,
  },
  output: distanceToGpsZoneM(
    { latitude: 37.5, longitude: 127.0 },
    {
      id: "circ1", gpsPolygon: [],
      projectionMeta: { shape: "circle", center: { latitude: 37.5, longitude: 127.0 }, radiusM: 20 },
    },
  ),
});
pushCase({
  id: "point_in_pixel_polygon_true",
  api: "pointInPixelPolygon",
  description: "픽셀 폴리곤(0,0)-(200,0)-(200,200)-(0,200) 안의 점(100,100) → true.",
  input: {
    point: { x: 100, y: 100 },
    polygon: [{ x: 0, y: 0 }, { x: 200, y: 0 }, { x: 200, y: 200 }, { x: 0, y: 200 }],
  },
  output: pointInPixelPolygon(
    { x: 100, y: 100 },
    [{ x: 0, y: 0 }, { x: 200, y: 0 }, { x: 200, y: 200 }, { x: 0, y: 200 }],
  ),
});
pushCase({
  id: "scale_pixel_polygon_to_frame_upscale_2x",
  api: "scalePixelPolygonToFrame",
  description: "베이스라인 960x540 폴리곤 → 현재 프레임 1920x1080(2배) 로 좌표 스케일 보정.",
  input: {
    polygon: [{ x: 100, y: 100 }, { x: 200, y: 200 }],
    projectionMeta: { refWidth: 960, refHeight: 540 },
    frame: { width: 1920, height: 1080 },
  },
  output: scalePixelPolygonToFrame(
    [{ x: 100, y: 100 }, { x: 200, y: 200 }],
    { refWidth: 960, refHeight: 540 },
    { width: 1920, height: 1080 },
  ),
});
pushCase({
  id: "project_foot_to_gps_nadir",
  api: "projectFootToGps",
  description: "정수직 nadir 자세 + 화면 중앙 발점 → 드론 GPS 위치 그대로(직하방).",
  input: { pose: NADIR_POSE, footXPx: 960, footYPx: 540, groundElevationM: 0 },
  output: projectFootToGps(NADIR_POSE, 960, 540),
});

// ── evaluateZoneIntrusion() — INSIDE/OUTSIDE/NEAR_BOUNDARY/UNKNOWN 각 2케이스 ──
const polyZone: DangerZone = { id: "poly1", name: "작업구역", gpsPolygon: SQUARE_POLY };
pushCase({
  id: "intrusion_inside_polygon_zone",
  api: "evaluateZoneIntrusion",
  description: "INSIDE(1/2, 폴리곤): 발점이 폴리곤 내부 → 이벤트 반환(inBuffer 없음).",
  input: { persons: [PERSON], zones: [polyZone], pose: NADIR_POSE, cfg, telemetrySkewMs: 0 },
  output: evaluateZoneIntrusion([PERSON], [polyZone], NADIR_POSE, cfg, 0),
});
const circleZone: DangerZone = {
  id: "circ1", gpsPolygon: [],
  projectionMeta: { shape: "circle", center: { latitude: 37.5, longitude: 127.0 }, radiusM: 20 },
};
pushCase({
  id: "intrusion_inside_circle_zone",
  api: "evaluateZoneIntrusion",
  description: "INSIDE(2/2, 원형): 발점이 원 반경 내부 → 정확한 원 거리 경로로 이벤트 반환.",
  input: { persons: [PERSON], zones: [circleZone], pose: NADIR_POSE, cfg, telemetrySkewMs: 0 },
  output: evaluateZoneIntrusion([PERSON], [circleZone], NADIR_POSE, cfg, 0),
});
const farPolyZone: DangerZone = {
  id: "polyfar",
  gpsPolygon: [
    { latitude: 37.9, longitude: 128.0 }, { latitude: 37.9, longitude: 128.001 },
    { latitude: 37.901, longitude: 128.001 }, { latitude: 37.901, longitude: 128.0 },
  ],
};
pushCase({
  id: "intrusion_outside_far_polygon_zone",
  api: "evaluateZoneIntrusion",
  description: "OUTSIDE(1/2, 폴리곤): 투영은 신뢰 가능하나 구역이 수십km 밖 → 빈 배열.",
  input: { persons: [PERSON], zones: [farPolyZone], pose: NADIR_POSE, cfg, telemetrySkewMs: 0 },
  output: evaluateZoneIntrusion([PERSON], [farPolyZone], NADIR_POSE, cfg, 0),
});
const farCircleZone: DangerZone = {
  id: "circfar", gpsPolygon: [],
  projectionMeta: { shape: "circle", center: { latitude: 37.9, longitude: 128.0 }, radiusM: 20 },
};
pushCase({
  id: "intrusion_outside_far_circle_zone",
  api: "evaluateZoneIntrusion",
  description: "OUTSIDE(2/2, 원형): 투영 신뢰 가능하나 원형 구역이 멀리 있음 → 빈 배열.",
  input: { persons: [PERSON], zones: [farCircleZone], pose: NADIR_POSE, cfg, telemetrySkewMs: 0 },
  output: evaluateZoneIntrusion([PERSON], [farCircleZone], NADIR_POSE, cfg, 0),
});
const nbPolyZone: DangerZone = {
  id: "nb_poly",
  gpsPolygon: [
    { latitude: 37.5 + 5 / 111320.0, longitude: 126.999 },
    { latitude: 37.5 + 5 / 111320.0, longitude: 127.001 },
    { latitude: 37.52, longitude: 127.001 },
    { latitude: 37.52, longitude: 126.999 },
  ],
  projectionMeta: { bufferM: 10 },
};
pushCase({
  id: "intrusion_near_boundary_polygon_buffer",
  api: "evaluateZoneIntrusion",
  description: (
    "NEAR_BOUNDARY(1/2, 폴리곤): 발점이 폴리곤 밖이지만 경계 +bufferM(10m) 이내 → " +
    "이벤트 반환 + inBuffer=true."
  ),
  input: { persons: [PERSON], zones: [nbPolyZone], pose: NADIR_POSE, cfg, telemetrySkewMs: 0 },
  output: evaluateZoneIntrusion([PERSON], [nbPolyZone], NADIR_POSE, cfg, 0),
});
const nbCircleZone: DangerZone = {
  id: "nb_circ", gpsPolygon: [],
  projectionMeta: {
    shape: "circle", center: { latitude: 37.5 + 8 / 111320.0, longitude: 127.0 },
    radiusM: 3, bufferM: 6,
  },
};
pushCase({
  id: "intrusion_near_boundary_circle_buffer",
  api: "evaluateZoneIntrusion",
  description: (
    "NEAR_BOUNDARY(2/2, 원형): 발점-중심 거리(~8m) > radiusM(3, 밖) 이지만 " +
    "거리-radiusM(~5m) <= bufferM(6) → inBuffer=true."
  ),
  input: { persons: [PERSON], zones: [nbCircleZone], pose: NADIR_POSE, cfg, telemetrySkewMs: 0 },
  output: evaluateZoneIntrusion([PERSON], [nbCircleZone], NADIR_POSE, cfg, 0),
});
pushCase({
  id: "intrusion_unknown_telemetry_too_old",
  api: "evaluateZoneIntrusion",
  description: (
    "UNKNOWN(1/2): telemetrySkewMs=5000(reject 등급) → GPS 투영 자체를 못 믿어 " +
    "구역(gps-only geometry) 평가 불가 → 빈 배열(OUTSIDE 아니라 '알 수 없음', 안전 " +
    "정직성 정책상 2D 대체 없이 침묵)."
  ),
  input: { persons: [PERSON], zones: [polyZone], pose: NADIR_POSE, cfg, telemetrySkewMs: 5000 },
  output: evaluateZoneIntrusion([PERSON], [polyZone], NADIR_POSE, cfg, 5000),
});
const horizontalPose = { ...NADIR_POSE, pitchDeg: -10 };
pushCase({
  id: "intrusion_unknown_gimbal_too_horizontal",
  api: "evaluateZoneIntrusion",
  description: (
    "UNKNOWN(2/2): pitchDeg=-10(minPitchDeg=-45 보다 수평) → projectionIsReliable=false, " +
    "gps-only 구역은 평가 불가 → 빈 배열(구역 밖이 아니라 판단 불가)."
  ),
  input: { persons: [PERSON], zones: [polyZone], pose: horizontalPose, cfg, telemetrySkewMs: 0 },
  output: evaluateZoneIntrusion([PERSON], [polyZone], horizontalPose, cfg, 0),
});

// ── 참고: 투영이 불신되어도 픽셀 폴리곤이 있으면 2D 폴백으로 판정 가능(UNKNOWN이 아님) ──
const pixelZone: DangerZone = {
  id: "pix1", gpsPolygon: [],
  pixelPolygon: [{ x: 900, y: 480 }, { x: 1100, y: 480 }, { x: 1100, y: 600 }, { x: 900, y: 600 }],
};
pushCase({
  id: "intrusion_pixel_polygon_fallback_when_gps_unreliable",
  api: "evaluateZoneIntrusion",
  description: (
    "GPS 투영 불신(pitch 수평)이어도 구역에 pixelPolygon(하위호환 image-space)이 있으면 " +
    "2D 발점 픽셀로 침입 판정(basis=pixel_polygon) — GPS 구역과 달리 침묵하지 않는다."
  ),
  input: {
    persons: [PERSON], zones: [pixelZone], pose: horizontalPose, cfg, telemetrySkewMs: 0,
    frame: { width: 1920, height: 1080 },
  },
  output: evaluateZoneIntrusion(
    [PERSON], [pixelZone], horizontalPose, cfg, 0, 0, { width: 1920, height: 1080 },
  ),
});

function tsxVersion(): string {
  try {
    return execSync("npx -y tsx --version", { encoding: "utf-8" }).trim();
  } catch {
    return "unknown";
  }
}

function jsonReplacer(_key: string, value: unknown): unknown {
  if (value instanceof Set) return [...value].sort();
  return value;
}

const doc = {
  source: {
    repo: "ksi-platform",
    commit: "030ebd5a",
    file: "ksi-safety/src/lib/zone-intrusion.ts",
  },
  extraction: {
    script: "tools/vector-extraction/capture_platform_zone.mts",
    runtime: {
      language: "node",
      version: process.version,
      runner: `npx -y tsx --tsconfig <ksi-safety>/tsconfig.json (${tsxVersion()}) — 네트워크 ` +
        "fetch 1회, node_modules 불필요. zone-intrusion.ts 체인은 순수 TS/JS(외부 npm 런타임 " +
        "의존 없음). package.json/node_modules 미변경(스크래치패드 실행).",
    },
  },
  tolerance: {
    abs: 1e-6,
    rel: 1e-9,
    rationale: (
      "이 벡터는 두 연산군을 섞는다. (1) WGS84 좌표 변환(enuToLatLng/projectFootToGps 의 " +
      "위경도 출력, 상수 나눗셈 1건뿐) → abs 1e-9 deg. (2) 등장방형 평면 근사 거리(m 단위: " +
      "distanceToGpsPolygonM/gpsDistanceM/distanceToGpsZoneM, cos(lat) 보정 1건 포함하는 " +
      "핀홀류 연산) → abs 1e-4 m. (3) inside/inBuffer/basis 등 판정 결과(불리언/문자열) → " +
      "정확히 일치(수치 tolerance 비적용). materializeCircleGpsPolygon 처럼 다각형 좌표를 " +
      "n개 도출하는 결과는 (1)과 동일 abs 1e-9 deg 를 적용한다. 최상위 abs/rel 은 " +
      "거리(m) 계열 기본값이고 세부는 tolerance.by_field 를 본다."
    ),
    by_field: {
      latitude: { abs: 1e-9, rel: 0 },
      longitude: { abs: 1e-9, rel: 0 },
    },
  },
  cases,
};

mkdirSync(dirname(OUT_PATH), { recursive: true });
writeFileSync(OUT_PATH, JSON.stringify(doc, jsonReplacer, 2) + "\n", "utf-8");
console.log(`wrote ${cases.length} cases -> ${OUT_PATH}`);
