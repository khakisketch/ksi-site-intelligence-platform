import { computePlaneBounds, formatPlaneValue, type PlaneUnit } from "./site-spatial";

/**
 * 만료·미준비 상태의 큰 범위 캔버스 — 사진이 아니다.
 *
 * - 검사 격자에서 유도한 파일 전체 사각형과, 같은 평면일 때만 겹치는 작업구역 링,
 *   그리고 실제 준비 창의 actualBounds를 네이티브 좌표 그대로 그린다.
 * - 재투영·유효 픽셀 단정·정확도 주장을 하지 않는다. 실제 픽셀은 그리지 않고
 *   범위·치수·축척만 등록 기록에서 계산한다.
 * - 가운데 큰 빈 상자 대신 "어디를 보고 있는지"를 먼저 보여 주고, 만료/미준비는
 *   캔버스 위의 짧은 상태와 우측 정보 패널의 행동으로 처리한다.
 *
 * Invariants: INV-020(네이티브 평면)/INV-024(정확도 주장 없음)/INV-040(가짜 픽셀 없음).
 */

const W = 900;
const H = 800;
const PAD = 96;

type Ring = Array<[number, number]>;

function unitSuffix(unit: PlaneUnit): string {
  return unit === "meters" ? " m" : unit === "degrees" ? "°" : "";
}

function niceMeterScale(span: number): number | null {
  if (!Number.isFinite(span) || span <= 0) return null;
  const candidates = [10, 20, 50, 100, 200, 500, 1000, 2000];
  const target = span / 4;
  return candidates.find((value) => value >= target) ?? candidates[candidates.length - 1]!;
}

function gridStep(span: number): number {
  if (span > 900) return 200;
  if (span > 400) return 100;
  if (span > 150) return 50;
  return 25;
}

export function SiteMosaicAbsentCanvas({
  fileRing,
  workAreaRing,
  overlaid,
  crsLabel,
  planeUnit,
  filePixelSize,
  preparedRing = null,
  preparedLabel = null,
}: {
  fileRing: Ring;
  workAreaRing: Ring | null;
  overlaid: boolean;
  crsLabel: string;
  planeUnit: PlaneUnit;
  filePixelSize: { width: number; height: number } | null;
  /** 실제 준비 기록의 actualBounds — 없으면 그리지 않는다. */
  preparedRing?: Ring | null;
  preparedLabel?: string | null;
}) {
  const showRing = overlaid && workAreaRing !== null && workAreaRing.length >= 3 ? workAreaRing : null;
  const contents = [...fileRing, ...(showRing ?? []), ...(preparedRing ?? [])];
  const bounds = computePlaneBounds(contents, null);
  const fileBounds = computePlaneBounds(fileRing, null);
  if (!bounds || !fileBounds || fileRing.length < 3) return null;

  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;
  const scale = Math.min((W - PAD * 2) / spanX, (H - PAD * 2) / spanY);
  const offsetX = (W - spanX * scale) / 2;
  const offsetY = (H - spanY * scale) / 2;
  const project = ([x, y]: readonly [number, number]): [number, number] => [
    offsetX + (x - bounds.minX) * scale,
    H - offsetY - (y - bounds.minY) * scale,
  ];
  const points = (ring: ReadonlyArray<readonly [number, number]>): string =>
    ring.map((point) => project(point).join(",")).join(" ");
  const fileProjected = fileRing.map((point) => project(point));
  const fileMinX = Math.min(...fileProjected.map(([x]) => x));
  const fileMaxX = Math.max(...fileProjected.map(([x]) => x));
  const fileMinY = Math.min(...fileProjected.map(([, y]) => y));
  const fileMaxY = Math.max(...fileProjected.map(([, y]) => y));
  const preparedProjected = preparedRing?.map((point) => project(point)) ?? null;
  const preparedMinX = preparedProjected ? Math.min(...preparedProjected.map(([x]) => x)) : 0;
  const preparedMinY = preparedProjected ? Math.min(...preparedProjected.map(([, y]) => y)) : 0;

  const fileWidth = fileBounds.maxX - fileBounds.minX;
  const fileHeight = fileBounds.maxY - fileBounds.minY;
  const meterScale = planeUnit === "meters" ? niceMeterScale(Math.max(fileWidth, fileHeight)) : null;
  const unit = unitSuffix(planeUnit);
  const pixelLabel = filePixelSize ? `${filePixelSize.width} × ${filePixelSize.height} px` : null;
  const stepMeters = planeUnit === "meters" ? gridStep(Math.max(fileWidth, fileHeight)) : null;
  const gridLines: { x1: number; y1: number; x2: number; y2: number; major: boolean }[] = [];
  if (stepMeters) {
    const [fminX, fminY, fmaxX, fmaxY] = [fileBounds.minX, fileBounds.minY, fileBounds.maxX, fileBounds.maxY];
    const startX = Math.ceil(fminX / stepMeters) * stepMeters;
    const startY = Math.ceil(fminY / stepMeters) * stepMeters;
    for (let x = startX; x <= fmaxX; x += stepMeters / 5) {
      const major = Math.abs(x / stepMeters - Math.round(x / stepMeters)) < 1e-6;
      const [px] = project([x, fminY]);
      gridLines.push({ x1: px, y1: fileMinY, x2: px, y2: fileMaxY, major });
    }
    for (let y = startY; y <= fmaxY; y += stepMeters / 5) {
      const major = Math.abs(y / stepMeters - Math.round(y / stepMeters)) < 1e-6;
      const [, py] = project([fminX, y]);
      gridLines.push({ x1: fileMinX, y1: py, x2: fileMaxX, y2: py, major });
    }
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid meet"
      className="absolute inset-0 block h-full w-full"
      role="img"
      aria-label={`등록 범위 도식. 실제 픽셀이 아니며 파일 전체 범위 ${formatPlaneValue(fileWidth, planeUnit)}${unit} × ${formatPlaneValue(fileHeight, planeUnit)}${unit}. ${showRing ? "실선은 작업구역 경계, 점선은 파일 전체 범위입니다." : "작업구역 경계는 같은 평면으로 확인되지 않아 표시하지 않았습니다."}${preparedLabel ? ` ${preparedLabel}의 실제 범위를 함께 표시합니다.` : ""}`}
    >
      <title>등록 범위 도식 — 실제 픽셀 아님</title>
      <defs>
        <pattern id="absentCanvasGrid" width="36" height="36" patternUnits="userSpaceOnUse">
          <path d="M36 0H0V36" fill="none" stroke="#1d2829" strokeWidth=".7" />
        </pattern>
        <clipPath id="absentExtentClip">
          <polygon points={points(fileRing)} />
        </clipPath>
      </defs>
      <rect width={W} height={H} fill="#121718" />
      <rect width={W} height={H} fill="url(#absentCanvasGrid)" />
      <g clipPath="url(#absentExtentClip)">
        {gridLines.map((line, index) => (
          <line
            key={index}
            x1={line.x1}
            y1={line.y1}
            x2={line.x2}
            y2={line.y2}
            stroke={line.major ? "#405351" : "#2a3838"}
            strokeWidth={line.major ? 1.1 : 0.7}
          />
        ))}
      </g>
      <polygon
        points={points(fileRing)}
        fill="none"
        stroke="#a9c0ca"
        strokeWidth="1.8"
        strokeDasharray="7 5"
        strokeLinejoin="round"
      />
      {showRing && (
        <polygon
          points={points(showRing)}
          fill="rgba(120,160,148,.055)"
          stroke="#ffffff"
          strokeWidth="3.2"
          strokeLinejoin="round"
        />
      )}
      {preparedRing && (
        <>
          <polygon
            points={points(preparedRing)}
            fill="rgba(125,154,169,.1)"
            stroke="#d9edf3"
            strokeWidth="2.2"
            strokeDasharray="4 3"
          />
          {preparedLabel && (
            <text x={preparedMinX} y={preparedMinY - 8} fontFamily="ui-monospace,monospace" fontSize="15" fill="#e5f3f7">
              {preparedLabel}
            </text>
          )}
        </>
      )}
      <g stroke="#e6ede9" strokeWidth="1.4">
        <path d={`M${fileMinX} ${fileMinY}v15M${fileMinX} ${fileMinY}h15`} />
        <path d={`M${fileMaxX} ${fileMaxY}v-15M${fileMaxX} ${fileMaxY}h-15`} />
        <path d={`M${fileMinX} ${fileMaxY}v-15M${fileMinX} ${fileMaxY}h15`} />
        <path d={`M${fileMaxX} ${fileMinY}v15M${fileMaxX} ${fileMinY}h-15`} />
      </g>

      {/* 실제 파일 범위의 치수 — 화면 픽셀이 아니라 검사 격자에서 계산한 평면 값. */}
      <g stroke="#c2d0c9" strokeWidth="1.1">
        <path d={`M${fileMinX} ${fileMaxY + 34}h${fileMaxX - fileMinX}M${fileMinX} ${fileMaxY + 29}v10M${fileMaxX} ${fileMaxY + 29}v10`} />
        <path d={`M${fileMinX - 34} ${fileMinY}v${fileMaxY - fileMinY}M${fileMinX - 39} ${fileMinY}h10M${fileMinX - 39} ${fileMaxY}h10`} />
      </g>
      <text x={(fileMinX + fileMaxX) / 2} y={fileMaxY + 52} textAnchor="middle" fontFamily="ui-monospace,monospace" fontSize="14" fill="#c2d0c9">
        {formatPlaneValue(fileWidth, planeUnit)}{unit}
      </text>
      <text x={fileMinX - 49} y={(fileMinY + fileMaxY) / 2} textAnchor="middle" transform={`rotate(-90 ${fileMinX - 49} ${(fileMinY + fileMaxY) / 2})`} fontFamily="ui-monospace,monospace" fontSize="14" fill="#c2d0c9">
        {formatPlaneValue(fileHeight, planeUnit)}{unit}
      </text>

      {meterScale !== null && (
        <g>
          <g stroke="#e2ebe6" strokeWidth="2">
            <path d={`M54 ${H - 64}v-18m-5 5 5-5 5 5`} />
            <path d={`M54 ${H - 82}h${meterScale * scale}`} />
            <path d={`M54 ${H - 82}v-6M${54 + meterScale * scale} ${H - 82}v-6`} />
          </g>
          <text x={64 + meterScale * scale} y={H - 76} fontFamily="ui-monospace,monospace" fontSize="15" fill="#e2ebe6">
            {meterScale} m
          </text>
        </g>
      )}

      <g fontFamily="ui-monospace,monospace" fill="#9fb0a8" fontSize="14">
        <text x={W - 26} y="36" textAnchor="end">{crsLabel}</text>
        {pixelLabel && <text x={W - 26} y={H - 26} textAnchor="end">{pixelLabel}</text>}
      </g>
    </svg>
  );
}
