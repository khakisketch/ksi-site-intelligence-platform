import { computePlaneBounds, formatPlaneValue, type PlaneUnit } from "./site-spatial";

/**
 * 준비된 픽셀이 없을 때의 범위 도식 — 사진이 아니다.
 *
 * - 그리는 것은 검사 격자에서 유도한 파일 전체 사각형과, 같은 평면일 때만
 *   겹치는 작업구역 링이다. 좌표 재해석·재투영을 하지 않는다.
 * - 사각형은 파일 전체 범위이며 빈틈(NoData) 없는 유효 픽셀로 읽지 않는다.
 * - 평면이 다르거나 확인할 수 없으면 작업구역을 겹쳐 그리지 않고 파일
 *   범위만 단독으로 둔다.
 *
 * Invariants: INV-020(네이티브 좌표 평면)/INV-024(정확도 주장 없음)/
 * INV-040(가짜 픽셀 없음)/INV-060·061(권한·이그레스 — 읽기 전용 도식).
 */

const VIEW_HEIGHT = 232;

function viewWidth(bounds: { minX: number; minY: number; maxX: number; maxY: number }): number {
  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;
  return Math.min(560, Math.max(160, Math.round((VIEW_HEIGHT * spanX) / spanY)));
}

function project(
  x: number,
  y: number,
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  width: number,
): [number, number] {
  const spanX = bounds.maxX - bounds.minX || 1;
  const spanY = bounds.maxY - bounds.minY || 1;
  const pad = 20;
  const scale = Math.min((width - pad * 2) / spanX, (VIEW_HEIGHT - pad * 2) / spanY);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (VIEW_HEIGHT - spanY * scale) / 2;
  return [offsetX + (x - bounds.minX) * scale, VIEW_HEIGHT - offsetY - (y - bounds.minY) * scale];
}

export function SiteMosaicAbsentDiagram({
  fileRing,
  workAreaRing,
  overlaid,
  overlayNote,
  crsLabel,
  planeUnit,
  filePixelSize,
  fileExtentLabel,
}: {
  /** 검사 격자에서 유도한 파일 전체 사각형 링 — 유효 픽셀 보장이 아니다. */
  fileRing: Array<[number, number]>;
  /** 같은 네이티브 평면의 작업구역 링 — overlaid일 때만 겹친다. */
  workAreaRing: Array<[number, number]> | null;
  /** 같은 평면으로 확인되어 겹쳐 그려도 되는지. */
  overlaid: boolean;
  /** 겹치지 않았을 때의 이유 한 줄. */
  overlayNote: string | null;
  crsLabel: string;
  planeUnit: PlaneUnit;
  filePixelSize: { width: number; height: number } | null;
  /** 함께 표시한 자료의 사람용 이름. */
  fileExtentLabel: string | null;
}) {
  const showRing = overlaid && workAreaRing !== null ? workAreaRing : null;
  const bounds = computePlaneBounds(showRing ? [...fileRing, ...showRing] : fileRing, null);
  if (!bounds || fileRing.length < 3) return null;
  const fileBounds = computePlaneBounds(fileRing, null);
  if (!fileBounds) return null;
  const width = viewWidth(bounds);
  const toPoints = (points: Array<[number, number]>) =>
    points.map(([x, y]) => project(x, y, bounds, width).join(",")).join(" ");
  const unitNote = planeUnit === "meters" ? "단위 m" : planeUnit === "degrees" ? "단위 °" : "단위 미확인";

  return (
    <figure className="overflow-hidden rounded-lg border border-line bg-sunk/40">
      <p className="border-b border-line px-3 py-1.5 text-[12px] font-bold text-ink-1">
        범위 도식 · 사진 아님
      </p>
      <svg
        viewBox={`0 0 ${width} ${VIEW_HEIGHT}`}
        className="block h-56 w-full text-ink-1"
        role="img"
        aria-label={`범위 도식. 점선은 파일 전체 범위이며 사진이 아닙니다.${showRing ? " 실선은 작업구역 경계입니다." : ""}`}
      >
        <title>범위 도식 — 사진 아님</title>
        <rect x={1} y={1} width={width - 2} height={VIEW_HEIGHT - 2} fill="none" stroke="currentColor" strokeOpacity={0.25} />
        {showRing && (
          <polygon points={toPoints(showRing)} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" />
        )}
        <polygon
          points={toPoints(fileRing)}
          fill="none"
          stroke="currentColor"
          strokeOpacity={showRing ? 0.6 : 1}
          strokeWidth={showRing ? 1.5 : 2}
          strokeDasharray="5 3"
          strokeLinejoin="round"
        />
      </svg>
      <figcaption className="border-t border-line px-3 py-2 text-[11.5px] leading-5 text-ink-2">
        <p>
          {showRing
            ? "실선은 작업구역 경계이며, 점선은 파일 전체 범위입니다."
            : "점선은 파일 전체 범위입니다."}
          {" "}사각형은 파일의 끝을 잰 값이며 빈틈 없는 유효 픽셀로 읽지 마세요. 사진이 아니며 정확도를 보증하지 않습니다.
        </p>
        {overlayNote && !showRing && <p className="mt-1">{overlayNote}</p>}
        <details className="mt-1">
          <summary className="tap-target cursor-pointer font-semibold">좌표·검사 격자 정보</summary>
          <dl className="mt-1 grid gap-1">
          <div><dt className="font-semibold text-ink-muted">위치 기준</dt><dd className="break-all font-mono">{crsLabel} · {unitNote}</dd></div>
          <div><dt className="font-semibold text-ink-muted">파일 전체 가로 범위</dt><dd className="break-all font-mono">{formatPlaneValue(fileBounds.minX, planeUnit)} – {formatPlaneValue(fileBounds.maxX, planeUnit)}</dd></div>
          <div><dt className="font-semibold text-ink-muted">파일 전체 세로 범위</dt><dd className="break-all font-mono">{formatPlaneValue(fileBounds.minY, planeUnit)} – {formatPlaneValue(fileBounds.maxY, planeUnit)}</dd></div>
          {filePixelSize && <div><dt className="font-semibold text-ink-muted">검사 격자</dt><dd>{filePixelSize.width} × {filePixelSize.height} 네이티브 픽셀</dd></div>}
          {fileExtentLabel && <div><dt className="font-semibold text-ink-muted">함께 표시한 자료</dt><dd className="break-words">{fileExtentLabel}</dd></div>}
          </dl>
        </details>
      </figcaption>
    </figure>
  );
}
