import { computePlaneBounds, formatPlaneValue, type PlaneUnit } from "./site-spatial";

/**
 * 원본 좌표 평면 SVG — 실제 꼭짓점을 그대로 옮긴 벡터 범위 미리보기.
 *
 * 위성사진이 아니며 정확도 인증도 아니다. OSM 축척에서 점으로만 보이는 작은
 * 투영좌표 구역이 "어디까지가 등록된 범위인가"를 눈으로 확인할 자리다.
 * 축 수치는 실제 범위에서 잰 값이며, 축척 막대는 미터 단위일 때만 그린다.
 * 좌표계가 알려지지 않은 평면은 단위를 단정하지 않는다. 두 축은 같은 자료
 * 단위로 그린다(한 축만 늘리지 않는다).
 */

const VIEW_HEIGHT = 260;

function viewWidth(bounds: { minX: number; minY: number; maxX: number; maxY: number }): number {
  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;
  return Math.min(640, Math.max(160, Math.round((VIEW_HEIGHT * spanX) / spanY)));
}

function project(
  x: number,
  y: number,
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  width: number,
): [number, number] {
  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;
  const pad = 24;
  const scale = Math.min((width - pad * 2) / spanX, (VIEW_HEIGHT - pad * 2) / spanY);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (VIEW_HEIGHT - spanY * scale) / 2;
  return [offsetX + (x - bounds.minX) * scale, VIEW_HEIGHT - offsetY - (y - bounds.minY) * scale];
}

/** 막대 길이를 1·2·5 계열의 읽기 좋은 값으로 고른다(표시용 어림, 원본은 그대로). */
function niceBarLength(span: number): number {
  if (!Number.isFinite(span) || span <= 0) return 0;
  const target = span / 4;
  const magnitude = 10 ** Math.floor(Math.log10(target));
  for (const factor of [5, 2, 1]) {
    if (magnitude * factor <= target) return magnitude * factor;
  }
  return magnitude / 10;
}

export function SiteNativeExtentSvg({
  boundary,
  footprint,
  crsLabel,
  footprintLabel,
  planeUnit,
  vertexCount,
  coincident,
  compact = false,
}: {
  boundary: Array<[number, number]>;
  footprint: Array<[number, number]> | null;
  crsLabel: string;
  footprintLabel: string | null;
  planeUnit: PlaneUnit;
  vertexCount: number;
  coincident: boolean;
  compact?: boolean;
}) {
  const bounds = computePlaneBounds(boundary, footprint);
  if (!bounds) return null;
  const width = viewWidth(bounds);
  const toPoints = (points: Array<[number, number]>) =>
    points.map(([x, y]) => project(x, y, bounds, width).join(",")).join(" ");
  const barLength = planeUnit === "meters" ? niceBarLength(bounds.maxX - bounds.minX) : 0;
  const unitNote = planeUnit === "meters" ? "단위 m" : planeUnit === "degrees" ? "단위 °" : "단위 미확인";

  return <figure className="overflow-hidden rounded-lg border border-line bg-surface">
    <svg
      viewBox={`0 0 ${width} ${VIEW_HEIGHT}`}
      className={compact ? "block h-36 w-full text-ink-1" : "block h-60 w-full text-ink-1 sm:h-80"}
      role="img"
      aria-label={`작업구역 경계${footprint ? ", 선택한 자료의 포함 범위 함께 표시" : ""}. ${planeUnit === "unknown" ? "좌표 단위 미확인." : ""}`}
    >
      <title>작업구역과 선택 자료의 범위</title>
      <rect x={1} y={1} width={width - 2} height={VIEW_HEIGHT - 2} fill="none" stroke="currentColor" strokeOpacity={0.25} />
      {footprint && !coincident && (
        <polygon points={toPoints(footprint)} fill="none" stroke="currentColor" strokeOpacity={0.55} strokeDasharray="5 3" strokeWidth={1.5} />
      )}
      {footprint && coincident && (
        <polygon points={toPoints(footprint)} fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinejoin="round" />
      )}
      {!coincident && (
        <polygon points={toPoints(boundary)} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" />
      )}
      {barLength > 0 && (() => {
        const [x1, y1] = project(bounds.minX, bounds.minY, bounds, width);
        const [x2] = project(bounds.minX + barLength, bounds.minY, bounds, width);
        const barY = y1 - 10;
        return <g stroke="currentColor" strokeWidth={2}>
          <line x1={x1} y1={barY} x2={x2} y2={barY} />
          <line x1={x1} y1={barY - 3} x2={x1} y2={barY + 3} />
          <line x1={x2} y1={barY - 3} x2={x2} y2={barY + 3} />
          <text x={(x1 + x2) / 2} y={barY - 6} textAnchor="middle" fontSize={11} fill="currentColor" stroke="none">{`${barLength} m`}</text>
        </g>;
      })()}
    </svg>
    <figcaption className="border-t border-line px-3 py-2 text-[11.5px] leading-5 text-ink-2">
      <p>실선은 작업구역{footprint ? (coincident ? "이며, 선택 자료의 포함 범위와 겹칩니다" : "이며, 점선은 선택 자료가 포함하는 범위입니다") : "의 경계입니다"}.
      {planeUnit === "unknown" && " 좌표 단위를 확인하지 못했습니다."} 사진이 아닌 범위 표시이며 정확도를 보증하지 않습니다.</p>
      <details className="mt-1">
        <summary className="tap-target cursor-pointer">좌표 정보 확인</summary>
        <dl className="mt-1 grid gap-1">
          <div><dt className="font-semibold">좌표계·단위</dt><dd>{crsLabel} · {unitNote}</dd></div>
          <div><dt className="font-semibold">경계 꼭짓점</dt><dd>{vertexCount}개</dd></div>
          <div><dt className="font-semibold">가로 좌표 범위</dt><dd className="break-all font-mono">{formatPlaneValue(bounds.minX, planeUnit)} – {formatPlaneValue(bounds.maxX, planeUnit)}</dd></div>
          <div><dt className="font-semibold">세로 좌표 범위</dt><dd className="break-all font-mono">{formatPlaneValue(bounds.minY, planeUnit)} – {formatPlaneValue(bounds.maxY, planeUnit)}</dd></div>
          {footprintLabel && <div><dt className="font-semibold">함께 표시한 자료</dt><dd className="break-words">{footprintLabel}</dd></div>}
        </dl>
        <p className="mt-1">지도 표시를 위한 좌표 변환은 원본 자료를 변경하지 않습니다.</p>
      </details>
    </figcaption>
  </figure>;
}
