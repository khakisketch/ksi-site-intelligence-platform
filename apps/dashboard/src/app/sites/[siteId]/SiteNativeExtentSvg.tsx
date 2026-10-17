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
}: {
  boundary: Array<[number, number]>;
  footprint: Array<[number, number]> | null;
  crsLabel: string;
  footprintLabel: string | null;
  planeUnit: PlaneUnit;
  vertexCount: number;
  coincident: boolean;
}) {
  const bounds = computePlaneBounds(boundary, footprint);
  if (!bounds) return null;
  const width = viewWidth(bounds);
  const toPoints = (points: Array<[number, number]>) =>
    points.map(([x, y]) => project(x, y, bounds, width).join(",")).join(" ");
  const midX = (bounds.minX + bounds.maxX) / 2;
  const midY = (bounds.minY + bounds.maxY) / 2;
  const barLength = planeUnit === "meters" ? niceBarLength(bounds.maxX - bounds.minX) : 0;
  const unitNote = planeUnit === "meters" ? "단위 m" : planeUnit === "degrees" ? "단위 °" : "단위 미확인";

  return <figure className="overflow-hidden rounded-lg border border-line bg-surface">
    <svg
      viewBox={`0 0 ${width} ${VIEW_HEIGHT}`}
      className="block h-60 w-full text-ink-1 sm:h-80"
      role="img"
      aria-label={`원본 좌표 평면의 등록 범위. 좌표계 ${crsLabel}, 꼭짓점 ${vertexCount}개${footprint ? ", 검사된 파일 footprint 함께 표시" : ""}.`}
    >
      <title>{`등록 범위 평면도 (${crsLabel})`}</title>
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
      <g fontSize={10} fill="currentColor" opacity={0.7}>
        <text x={4} y={VIEW_HEIGHT - 8}>{formatPlaneValue(bounds.minX, planeUnit)}</text>
        <text x={width / 2} y={VIEW_HEIGHT - 8} textAnchor="middle">{formatPlaneValue(midX, planeUnit)}</text>
        <text x={width - 4} y={VIEW_HEIGHT - 8} textAnchor="end">{formatPlaneValue(bounds.maxX, planeUnit)}</text>
        <text x={4} y={14}>{formatPlaneValue(bounds.maxY, planeUnit)}</text>
        <text x={4} y={VIEW_HEIGHT / 2}>{formatPlaneValue(midY, planeUnit)}</text>
      </g>
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
      원본 좌표 평면 · {crsLabel} · {unitNote} · 꼭짓점 {vertexCount}개.
      실선은 작업구역 경계{footprint ? (coincident ? "이며, 파일 범위와 작업구역 경계가 겹쳐 표시됩니다" : `이며, 점선은 ${footprintLabel ?? "선택된 파일"}의 검사된 footprint입니다`) : "입니다"}.
      위성사진이 아니며 겹침은 정확도 인증이 아닙니다.
    </figcaption>
  </figure>;
}
