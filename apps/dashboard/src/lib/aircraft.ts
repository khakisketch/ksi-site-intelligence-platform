/**
 * 운용 기체(DJI Matrice 4D) 기본값 — 위저드들이 공유하는 단일 출처.
 *
 * 기종·페이로드 값 정본: DJI Cloud API Product Support "Enumeration Values"
 * (2026-08-18 확인) — M4D: droneEnumValue 100/sub 0, 광각 카메라 payloadEnumValue 98.
 * https://developer.dji.com/doc/cloud-api-tutorial/en/overview/product-support.html
 * 실기 Pilot 2 가 이 값을 수용하는지는 FIELD-0a 에서 확정한다.
 */
export const M4D_DRONE = {
  droneEnumValue: 100,
  droneSubEnumValue: 0,
  payloadEnumValue: 98,
} as const;

/**
 * M4D 광각 카메라 — DJI 공식 스펙(4/3 CMOS 20MP, 5280×3956, FOV 84°, 35mm 환산
 * 24mm — enterprise.dji.com/dock-3/specs, 2026-08-18 확인)에서 유도한 값.
 * 센서 폭 17.3mm 는 4/3형 공칭값이다. 실초점거리는 2026-08-20 FIELD-0a 원본 M4D
 * WideCamera EXIF에서 12.29mm(5280×3956, 35mm 환산 24mm)로 확인해 유도값 12.0mm를
 * 교체했다. 이 파일이 두 위저드의 단일 출처라 서버가 간격을 다시 계산한다.
 */
export const M4D_WIDE_CAMERA = {
  sensorWidthMm: 17.3,
  focalLengthMm: 12.29,
  imageWidthPx: 5280,
  imageHeightPx: 3956,
} as const;
