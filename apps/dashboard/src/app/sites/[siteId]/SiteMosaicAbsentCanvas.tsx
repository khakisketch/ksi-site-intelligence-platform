import { useId } from "react";
import { computePlaneBounds, formatPlaneValue, nativeScaleBarLength, type PlaneUnit } from "./site-spatial";

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

/** 좌표 간격으로부터 눈금을 생성한다. 화면의 선 개수는 파일 크기와 독립적이다. */
function nativeGridTicks(min: number, max: number, majorStep: number) {
  const step = majorStep / 5;
  if (step <= 0 || !Number.isFinite(step)) return [];
  const first = Math.ceil(min / step);
  const last = Math.floor(max / step);
  if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last)) return [];
  const count = Math.min(64, Math.max(0, last - first + 1));
  return Array.from({ length: count }, (_, offset) => {
    const index = first + offset;
    return { value: index * step, major: index % 5 === 0 };
  });
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
  const id = useId();
  const showRing = overlaid && workAreaRing !== null && workAreaRing.length >= 3 ? workAreaRing : null;
  const contents = [...fileRing, ...(showRing ?? []), ...(preparedRing ?? [])];
  const bounds = computePlaneBounds(contents, null);
  const fileBounds = computePlaneBounds(fileRing, null);
  if (!bounds || !fileBounds || fileRing.length < 3) return null;

  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;
  const scale = Math.min((W - PAD * 2) / spanX, (H - PAD * 2) / spanY);
  if (!Number.isFinite(scale) || scale <= 0) return null;
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
  const meterScale = planeUnit === "meters" ? nativeScaleBarLength(Math.max(fileWidth, fileHeight)) : 0;
  const unit = unitSuffix(planeUnit);
  const extentLabel = `${formatPlaneValue(fileWidth, planeUnit)}${unit} × ${formatPlaneValue(fileHeight, planeUnit)}${unit}`;
  const pixelLabel = filePixelSize ? `${filePixelSize.width} × ${filePixelSize.height} px` : null;
  const gridLines = [
    ...nativeGridTicks(fileBounds.minX, fileBounds.maxX, meterScale).map(({ value, major }) => {
      const [x] = project([value, fileBounds.minY]);
      return { x1: x, y1: fileMinY, x2: x, y2: fileMaxY, major };
    }),
    ...nativeGridTicks(fileBounds.minY, fileBounds.maxY, meterScale).map(({ value, major }) => {
      const [, y] = project([fileBounds.minX, value]);
      return { x1: fileMinX, y1: y, x2: fileMaxX, y2: y, major };
    }),
  ];

  return (
    <div className="relative min-h-[240px] flex-1 overflow-hidden rounded-lg border border-line bg-sidebar sm:min-h-[340px]">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        className="absolute inset-0 block h-full w-full"
        role="img"
        aria-label={`등록 범위 도식. 실제 픽셀이 아니며 파일 전체 범위 ${extentLabel}. ${showRing ? "실선은 작업구역 경계, 점선은 파일 전체 범위입니다." : "작업구역 경계는 같은 평면으로 확인되지 않아 표시하지 않았습니다."}${preparedLabel ? ` ${preparedLabel}의 실제 범위를 함께 표시합니다.` : ""}`}
      >
        <title>등록 범위 도식 — 실제 픽셀 아님</title>
        <desc>{[crsLabel, pixelLabel].filter(Boolean).join(" · ")}</desc>
        <defs>
          <pattern id={`${id}-grid`} width="36" height="36" patternUnits="userSpaceOnUse">
            <path d="M36 0H0V36" fill="none" style={{ stroke: "var(--stage-grid)" }} strokeWidth=".7" />
          </pattern>
          <clipPath id={`${id}-extent`}>
            <polygon points={points(fileRing)} />
          </clipPath>
        </defs>
        <rect width={W} height={H} style={{ fill: "var(--stage)" }} />
        <rect width={W} height={H} fill={`url(#${id}-grid)`} />
        <g clipPath={`url(#${id}-extent)`}>
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
        <g className="hidden lg:block">
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

          {meterScale > 0 && (
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

        </g>
      </svg>
      <span className="absolute left-3 top-3 rounded border border-white/15 bg-black/55 px-2 py-1 font-mono text-micro text-sidebar-text backdrop-blur-sm">
        등록 범위 · 실제 픽셀 아님
      </span>
      <span aria-hidden="true" className="absolute right-3 top-3 rounded bg-black/55 px-2 py-1 font-mono text-micro text-sidebar-text">{crsLabel}</span>
      <div aria-hidden="true" className="absolute inset-x-3 bottom-2 flex items-end justify-between gap-2 font-mono text-micro text-sidebar-text">
        <span className="rounded bg-black/55 px-2 py-1 lg:invisible">{extentLabel}</span>
        {pixelLabel && <span className="rounded bg-black/55 px-2 py-1">{pixelLabel}</span>}
      </div>
    </div>
  );
}
