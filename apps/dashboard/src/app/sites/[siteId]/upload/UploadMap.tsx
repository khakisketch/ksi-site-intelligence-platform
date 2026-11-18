import type { LonLat } from "@/lib/geo/geotiff-footprint";

export type MapFootprint = { key: string; label: string; ring: readonly LonLat[] };

/**
 * 작업구역(점선)과 올릴 파일의 범위(색 면)를 겹쳐 그린다 — "맞는 곳의 자료인가"를 글 없이 눈으로 보게 한다.
 * 배경 지도 없이 경위도를 위도 보정한 평면에 그리는 개략도이며 측량 도면이 아니다.
 */
export function projectRings(rings: readonly (readonly LonLat[])[], width: number, height: number, pad = 0.12) {
  const all = rings.flat();
  if (all.length === 0) return { rings: rings.map(() => ""), ok: false };
  const lat0 = (Math.min(...all.map(([, lat]) => lat)) + Math.max(...all.map(([, lat]) => lat))) / 2;
  const kx = Math.cos((lat0 * Math.PI) / 180);
  const xs = all.map(([lon]) => lon * kx);
  const ys = all.map(([, lat]) => lat);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1e-9);
  const spanY = Math.max(maxY - minY, 1e-9);
  const scale = Math.min((width * (1 - 2 * pad)) / spanX, (height * (1 - 2 * pad)) / spanY);
  const offX = (width - spanX * scale) / 2;
  const offY = (height - spanY * scale) / 2;
  return {
    ok: true,
    rings: rings.map((ring) => ring.map(([lon, lat]) => `${(offX + (lon * kx - minX) * scale).toFixed(1)},${(offY + (maxY - lat) * scale).toFixed(1)}`).join(" ")),
  };
}

const FILL: Record<string, string> = { ortho: "var(--mid)", dsm: "var(--ink-muted)" };

export function UploadMap({ area, areaName, footprints, className = "" }: { area: readonly LonLat[] | null; areaName: string; footprints: readonly MapFootprint[]; className?: string }) {
  const W = 800;
  const H = 520;
  const projected = projectRings([...(area ? [area] : []), ...footprints.map((item) => item.ring)], W, H);
  const areaPoints = area ? projected.rings[0] : null;
  const footPoints = footprints.map((item, index) => ({ item, points: projected.rings[(area ? 1 : 0) + index]! }));
  const description = footprints.length === 0
    ? `작업구역 ${areaName}`
    : `작업구역 ${areaName} 위에 올릴 파일 ${footprints.map((item) => item.label).join(", ")}의 범위`;
  return (
    <div className={`upload-map relative overflow-hidden rounded-xl border border-line ${className}`.trim()} style={{ background: "var(--sunk)" }}>
      <svg role="img" aria-label={description} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" className="absolute inset-0 h-full w-full">
        <defs>
          <pattern id="upload-map-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="var(--line)" strokeWidth="1" /></pattern>
        </defs>
        <rect width={W} height={H} fill="url(#upload-map-grid)" />
        {footPoints.map(({ item, points }) => (
          <polygon key={item.key} points={points} fill={FILL[item.key] ?? "var(--ink-muted)"} fillOpacity={0.35} stroke={FILL[item.key] ?? "var(--ink-muted)"} strokeWidth={3} />
        ))}
        {areaPoints ? <polygon points={areaPoints} fill="none" stroke="var(--ink-1)" strokeWidth={2.5} strokeDasharray="8 6" /> : null}
      </svg>
      <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-3 rounded-full border border-line bg-surface px-3 py-1 text-caption text-ink-2">
        {footprints.map((item) => (
          <span key={item.key} className="inline-flex items-center gap-1.5"><span aria-hidden className="inline-block size-2.5 rounded-sm" style={{ background: FILL[item.key] ?? "var(--ink-muted)" }} />{item.label}</span>
        ))}
        <span className="inline-flex items-center gap-1.5"><span aria-hidden className="inline-block h-2.5 w-4 rounded-sm border-2 border-dashed border-ink-1" />{areaName}</span>
      </div>
    </div>
  );
}
