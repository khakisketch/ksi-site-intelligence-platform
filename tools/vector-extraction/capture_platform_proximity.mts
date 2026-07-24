/**
 * KSI Platform ksi-safety proximity-distance.ts 골든 벡터 캡처 (P0-3).
 *
 * 원 구현(참고, 읽기전용):
 *   references/repos/ksi-platform/ksi-safety/src/lib/proximity-distance.ts
 *   @030ebd5a (ksi-platform HEAD, verify_reference_pins.sh 대상)
 *
 * 이 스크립트는 projectPixelToGroundEnu()/resolveTelemetryTier()/evaluateProximityReal()/
 * evaluateProximity()/equipmentGroundZoneM() 를 **실제로 실행**해 입력→출력을 캡처한다
 * (손 전사 금지, 대표자 반영사항 8). 출력은
 * packages/test-vectors/vectors/legacy_compat/proximity_distance.json 에 쓴다.
 *
 * 실행 방법(재추출):
 *   cd tools/vector-extraction && npx -y tsx capture_platform_proximity.mts
 *   (네트워크 가능 환경에서 tsx 를 1회 fetch — package.json/node_modules 불필요.
 *    이 파일이 import 하는 proximity-distance.ts → proximity.ts → safety-zone.ts 체인은
 *    순수 TS/JS 로 next.js/react/zod 등 런타임 npm 의존이 전혀 없어 tsx 단독으로 실행된다.)
 *
 * 이 스크립트는 tools/vector-extraction/ 아래에 있어 scripts/check_no_reference_imports.sh
 * 가드(CODE_DIRS=apps/services/edge/workers/packages/tests) 대상이 아니다 — tools/ 는
 * 가드 제외 디렉토리로, references/ 를 직접 import 해도 되는 유일한 위치다(README.md 참고).
 */

import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_PROXIMITY_CONFIG,
  equipmentGroundZoneM,
  evaluateProximity,
  evaluateProximityReal,
  projectPixelToGroundEnu,
  resolveTelemetryTier,
  type GroundProjectionPose,
  type MotionSignal,
} from "../../references/repos/ksi-platform/ksi-safety/src/lib/proximity-distance.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..", "..");
const OUT_PATH = resolve(
  REPO_ROOT,
  "packages/test-vectors/vectors/legacy_compat/proximity_distance.json",
);

const cfg = DEFAULT_PROXIMITY_CONFIG;

type Detection = {
  class?: string;
  confidence?: number;
  bbox_xyxy?: number[];
  track_id?: number;
  velocity_px?: number[];
};

const NADIR_POSE: GroundProjectionPose = {
  altitudeM: 30, pitchDeg: -90, yawDeg: 0, rollDeg: 0, hfovDeg: 70, imgW: 1920, imgH: 1080,
};
const NADIR_DRONE_POSE = { ...NADIR_POSE, lat: 37.5, lng: 127.0 };
const EXCAVATOR: Detection = { class: "excavator", bbox_xyxy: [900, 480, 1100, 600] };

function personAt(x: number): Detection {
  return { class: "person", bbox_xyxy: [x, 500, x + 20, 560] };
}

type CaseRecord = {
  id: string;
  api: string;
  description: string;
  input: unknown;
  output: unknown;
};

const cases: CaseRecord[] = [];

function pushCase(rec: CaseRecord): void {
  cases.push(rec);
}

// ── projectPixelToGroundEnu() ──────────────────────────────────────────────
pushCase({
  id: "ground_enu_nadir_center",
  api: "projectPixelToGroundEnu",
  description: "짐벌 정수직(-90도) 중앙 픽셀 → 접지점 ENU ≈ (0,0) (기체 직하방).",
  input: { pose: NADIR_POSE, px: 960, py: 540, groundElevationM: 0 },
  output: projectPixelToGroundEnu(NADIR_POSE, 960, 540),
});
pushCase({
  id: "ground_enu_horizontal_pitch_returns_null",
  api: "projectPixelToGroundEnu",
  description: "pitch=0(완전 수평) → 광선이 지면과 평행/위 → null(수평선 위, 외삽 없음).",
  input: { pose: { ...NADIR_POSE, pitchDeg: 0 }, px: 960, py: 540, groundElevationM: 0 },
  output: projectPixelToGroundEnu({ ...NADIR_POSE, pitchDeg: 0 }, 960, 540),
});
pushCase({
  id: "ground_enu_oblique_with_roll",
  api: "projectPixelToGroundEnu",
  description: "pitch=-60, roll=15 → roll 보정된 카메라 기저로 접지점이 옆으로 치우침.",
  input: {
    pose: { ...NADIR_POSE, pitchDeg: -60, rollDeg: 15, yawDeg: 30 },
    px: 1200, py: 700, groundElevationM: 0,
  },
  output: projectPixelToGroundEnu(
    { ...NADIR_POSE, pitchDeg: -60, rollDeg: 15, yawDeg: 30 }, 1200, 700,
  ),
});
pushCase({
  id: "ground_enu_ground_elevation_offset_reduces_effective_altitude",
  api: "projectPixelToGroundEnu",
  description: (
    "groundElevationM=10(대상 지면이 이륙기준보다 높음) → 유효고도 감소로 접지점이 더 가까워짐."
  ),
  input: { pose: NADIR_POSE, px: 1200, py: 540, groundElevationM: 10 },
  output: projectPixelToGroundEnu(NADIR_POSE, 1200, 540, 10),
});

// ── resolveTelemetryTier() — 3단계 신선도 게이트 ───────────────────────────
pushCase({
  id: "telemetry_tier_fresh",
  api: "resolveTelemetryTier",
  description: "skew=100ms <= telemetryFreshMs(300) → fresh(추가조건 없이 즉시 신뢰).",
  input: { telemetrySkewMs: 100, cfg, motion: null },
  output: resolveTelemetryTier(100, cfg),
});
pushCase({
  id: "telemetry_tier_stale_but_calm_motion_allowed",
  api: "resolveTelemetryTier",
  description: (
    "skew=1000ms(창 안) + 기체 안정(속도/yaw/짐벌율 모두 calm 이하) → stale(허용, 중신뢰로 강등)."
  ),
  input: {
    telemetrySkewMs: 1000, cfg,
    motion: { speedMps: 0.2, yawRateDps: 1, gimbalRateDps: 1 } as MotionSignal,
  },
  output: resolveTelemetryTier(1000, cfg, { speedMps: 0.2, yawRateDps: 1, gimbalRateDps: 1 }),
});
pushCase({
  id: "telemetry_tier_stale_unknown_motion_rejected",
  api: "resolveTelemetryTier",
  description: (
    "skew=1000ms(창 안) + motion 정보 없음(모름) → 보수적으로 reject " +
    "(\"모르면 못 믿는다\", TELEMETRY_TOO_OLD)."
  ),
  input: { telemetrySkewMs: 1000, cfg, motion: null },
  output: resolveTelemetryTier(1000, cfg),
});
pushCase({
  id: "telemetry_tier_reject_aircraft_moving_too_fast",
  api: "resolveTelemetryTier",
  description: "skew=1000ms + speedMps=5 > telemetryCalmSpeedMps(1) → AIRCRAFT_MOVING_TOO_FAST.",
  input: { telemetrySkewMs: 1000, cfg, motion: { speedMps: 5 } as MotionSignal },
  output: resolveTelemetryTier(1000, cfg, { speedMps: 5 }),
});
pushCase({
  id: "telemetry_tier_reject_gimbal_changing",
  api: "resolveTelemetryTier",
  description: (
    "skew=1000ms + 속도/yaw 는 calm, gimbalRateDps=50 > telemetryCalmGimbalDps(10) → " +
    "GIMBAL_CHANGING."
  ),
  input: {
    telemetrySkewMs: 1000, cfg,
    motion: { speedMps: 0.1, yawRateDps: 1, gimbalRateDps: 50 } as MotionSignal,
  },
  output: resolveTelemetryTier(1000, cfg, { speedMps: 0.1, yawRateDps: 1, gimbalRateDps: 50 }),
});
pushCase({
  id: "telemetry_tier_reject_too_old",
  api: "resolveTelemetryTier",
  description: "skew=5000ms > telemetryMaxSkewMs(2000) → 항상 reject(TELEMETRY_TOO_OLD).",
  input: { telemetrySkewMs: 5000, cfg, motion: null },
  output: resolveTelemetryTier(5000, cfg),
});

// ── evaluateProximityReal() / evaluateProximity() — 사람-장비 근접 거리 판정 ──
pushCase({
  id: "proximity_real_critical_within_alert_radius",
  api: "evaluateProximityReal",
  description: "사람 발점이 장비 위험구역 빨강 반경(rAlertM) 안 → severity=critical.",
  input: {
    persons: [personAt(950)], equipment: [EXCAVATOR], pose: NADIR_DRONE_POSE, cfg, tier: "fresh",
  },
  output: evaluateProximityReal([personAt(950)], [EXCAVATOR], NADIR_DRONE_POSE, cfg, "fresh"),
});
pushCase({
  id: "proximity_real_medium_within_warn_band",
  api: "evaluateProximityReal",
  description: "사람 발점이 빨강~노랑 사이(rAlertM < dist <= rWarnM) → severity=medium.",
  input: {
    persons: [personAt(650)], equipment: [EXCAVATOR], pose: NADIR_DRONE_POSE, cfg, tier: "fresh",
  },
  output: evaluateProximityReal([personAt(650)], [EXCAVATOR], NADIR_DRONE_POSE, cfg, "fresh"),
});
pushCase({
  id: "proximity_real_none_outside_warn_band",
  api: "evaluateProximityReal",
  description: "사람 발점이 노랑 반경 밖(rWarnM 초과) → 이벤트 없음(빈 배열).",
  input: {
    persons: [personAt(50)], equipment: [EXCAVATOR], pose: NADIR_DRONE_POSE, cfg, tier: "fresh",
  },
  output: evaluateProximityReal([personAt(50)], [EXCAVATOR], NADIR_DRONE_POSE, cfg, "fresh"),
});
pushCase({
  id: "proximity_real_stale_tier_degrades_confidence_to_medium",
  api: "evaluateProximityReal",
  description: "tier='stale'(허용됐지만 오래된 텔레메트리) → severity 동일, confidence만 medium.",
  input: {
    persons: [personAt(950)], equipment: [EXCAVATOR], pose: NADIR_DRONE_POSE, cfg, tier: "stale",
  },
  output: evaluateProximityReal([personAt(950)], [EXCAVATOR], NADIR_DRONE_POSE, cfg, "stale"),
});
pushCase({
  id: "proximity_pitch_too_horizontal_falls_back_to_2d",
  api: "evaluateProximity",
  description: (
    "pitch=-10 > minPitchDeg(-45, 즉 너무 수평) → 지면투영 불신, 화면좌표 2D 폴백" +
    "(basis=image_2d, distanceM=null)."
  ),
  input: {
    persons: [personAt(950)], equipment: [EXCAVATOR],
    pose: { ...NADIR_DRONE_POSE, pitchDeg: -10 },
    frame: { width: 1920, height: 1080 }, cfg, telemetrySkewMs: 0,
  },
  output: evaluateProximity(
    [personAt(950)], [EXCAVATOR], { ...NADIR_DRONE_POSE, pitchDeg: -10 },
    { width: 1920, height: 1080 }, cfg, 0,
  ),
});
pushCase({
  id: "proximity_reject_tier_falls_back_to_2d",
  api: "evaluateProximity",
  description: (
    "pitch 는 충분히 아래를 보지만 telemetrySkewMs=5000(reject 등급) → 2D 폴백" +
    "(GPS/지면투영 대신 화면좌표)."
  ),
  input: {
    persons: [personAt(950)], equipment: [EXCAVATOR], pose: NADIR_DRONE_POSE,
    frame: { width: 1920, height: 1080 }, cfg, telemetrySkewMs: 5000,
  },
  output: evaluateProximity(
    [personAt(950)], [EXCAVATOR], NADIR_DRONE_POSE,
    { width: 1920, height: 1080 }, cfg, 5000,
  ),
});

// ── equipmentGroundZoneM() — footprint 신뢰도에 따른 최소반경 하한 조건부 적용 ──
pushCase({
  id: "equipment_zone_credible_footprint_no_min_clamp",
  api: "equipmentGroundZoneM",
  description: (
    "장비 bbox 가 넓어(투영 footprint >= credibleFootprintM 2.0m) 실측 신뢰 → " +
    "minAlertRadiusM/minWarnRadiusM 하한 미적용(실측 그대로)."
  ),
  input: { pose: NADIR_POSE, equipment: EXCAVATOR, cfg },
  output: equipmentGroundZoneM(NADIR_POSE, EXCAVATOR, cfg),
});
pushCase({
  id: "equipment_zone_small_footprint_clamped_to_minimum_radius",
  api: "equipmentGroundZoneM",
  description: (
    "장비 bbox 가 작아(투영 footprint < credibleFootprintM) 실측 불신 → " +
    "minAlertRadiusM(3m)/minWarnRadiusM(5m) 안전망 하한이 발동."
  ),
  input: {
    pose: NADIR_POSE,
    equipment: { class: "excavator", bbox_xyxy: [955, 530, 965, 545] } as Detection,
    cfg,
  },
  output: equipmentGroundZoneM(
    NADIR_POSE, { class: "excavator", bbox_xyxy: [955, 530, 965, 545] }, cfg,
  ),
});

function tsxVersion(): string {
  try {
    return execSync("npx -y tsx --version", { encoding: "utf-8" }).trim();
  } catch {
    return "unknown";
  }
}

const doc = {
  source: {
    repo: "ksi-platform",
    commit: "030ebd5a",
    file: "ksi-safety/src/lib/proximity-distance.ts",
  },
  extraction: {
    script: "tools/vector-extraction/capture_platform_proximity.mts",
    runtime: {
      language: "node",
      version: process.version,
      runner: `npx -y tsx (${tsxVersion()}) — 네트워크 fetch 1회, node_modules 불필요. ` +
        "proximity-distance.ts→proximity.ts→safety-zone.ts 체인은 순수 TS/JS(외부 npm " +
        "런타임 의존 없음). package.json/node_modules 미변경(스크래치패드 실행).",
    },
  },
  tolerance: {
    abs: 1e-6,
    rel: 1e-9,
    rationale: (
      "이 벡터는 삼각함수 기반 카메라 기저(cameraBasis: sin/cos/atan/normalize)로 만든 " +
      "핀홀 광선-평면 교차다. ENU 결과([east_m, north_m], m) → abs 1e-4 m " +
      "(부동소수 반복 연산이지만 단일 스케일 나눗셈이라 스케일 원리 반경 오차는 이 이하); " +
      "distanceM/distanceToZoneM/rAlertM/rWarnM(m) → abs 1e-2 m (원 구현이 " +
      "Math.round(x*100)/100 으로 이미 소수 둘째자리까지 반올림해 반환하므로, 그 반올림 " +
      "정밀도가 비교 기준); tier/reason/severity/basis 등 열거형 문자열 → 정확히 일치" +
      "(수치 tolerance 비적용, 문자열 동등비교). 최상위 abs/rel 은 ENU 미터 계열 기본값."
    ),
    by_field: {
      east_m: { abs: 1e-4, rel: 0 },
      north_m: { abs: 1e-4, rel: 0 },
      distanceM: { abs: 1e-2, rel: 0 },
      distanceToZoneM: { abs: 1e-2, rel: 0 },
      rAlertM: { abs: 1e-4, rel: 0 },
      rWarnM: { abs: 1e-4, rel: 0 },
    },
  },
  cases,
};

// cfg.swingClasses/motionClasses 는 Set — JSON.stringify 기본 동작은 Set 을 {} 로 지워버리므로
// (열거 가능한 프로퍼티가 없음) 배열로 풀어서 직렬화한다(입력 필드의 실제 값을 정직하게 기록).
function jsonReplacer(_key: string, value: unknown): unknown {
  if (value instanceof Set) return [...value].sort();
  return value;
}

mkdirSync(dirname(OUT_PATH), { recursive: true });
writeFileSync(OUT_PATH, JSON.stringify(doc, jsonReplacer, 2) + "\n", "utf-8");
console.log(`wrote ${cases.length} cases -> ${OUT_PATH}`);
