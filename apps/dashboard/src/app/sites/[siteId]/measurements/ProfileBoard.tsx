import type { ProfileSample } from "@/lib/core-api/measurement-types";
import { nearestSample } from "@/lib/measurement-profile";

import type { DistanceRange } from "./ProfileChart";

const W = 600;
const H = 400;
const PAD = 70;

interface Frame {
  project: (x: number, y: number) => [number, number];
}

/** 지점 좌표(격자 좌표계, 북쪽이 위)를 같은 축척으로 화면에 맞춘다. 좌표계 변환은 하지 않는다. */
function frameFor(samples: readonly ProfileSample[]): Frame {
  const xs = samples.map((row) => row.x);
  const ys = samples.map((row) => row.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY, 1e-9);
  const scale = Math.min(W - PAD * 2, H - PAD * 2) / span;
  const offsetX = (W - (maxX - minX) * scale) / 2;
  const offsetY = (H - (maxY - minY) * scale) / 2;
  return { project: (x, y) => [offsetX + (x - minX) * scale, H - (offsetY + (y - minY) * scale)] };
}

function points(rows: readonly ProfileSample[], frame: Frame): string {
  return rows.map((row) => frame.project(row.x, row.y).map((value) => value.toFixed(1)).join(",")).join(" ");
}

/**
 * 측정 선을 어두운 계측 면 위에 그린다. 지도 타일이나 영상이 아니며, 범위를 추정해 그리지 않는다.
 * 그래프에서 고른 지점과 구간이 같은 선 위에 표시된다.
 */
export function ProfileBoard({
  samples,
  lineLengthM,
  probeM,
  range,
  caption,
}: {
  samples: readonly ProfileSample[];
  lineLengthM: number;
  probeM: number | null;
  range: DistanceRange | null;
  caption: string;
}) {
  const frame = frameFor(samples);
  const first = samples[0]!;
  const last = samples[samples.length - 1]!;
  const [ax, ay] = frame.project(first.x, first.y);
  const [bx, by] = frame.project(last.x, last.y);
  const probe = probeM === null ? null : nearestSample(samples, probeM);
  const [px, py] = probe ? frame.project(probe.x, probe.y) : [0, 0];
  const a = range ? Math.min(range.a, range.b) : null;
  const b = range ? Math.max(range.a, range.b) : null;
  const selected = a !== null && b !== null && b > a ? samples.filter((row) => row.distanceM >= a && row.distanceM <= b) : [];

  return (
    <section aria-label="측정 선 위치" className="overflow-hidden rounded-xl" style={{ background: "var(--stage)", color: "#dce4e6" }}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`측정 선 위치. ${caption}`} className="block h-auto w-full">
        <defs>
          <pattern id="profile-board-grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M40 0H0V40" fill="none" stroke="var(--stage-grid)" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width={W} height={H} fill="url(#profile-board-grid)" />
        {selected.length > 1 && (
          <polyline data-testid="profile-board-range" points={points(selected, frame)} fill="none" stroke="#9fb4b8" strokeWidth="10" strokeLinecap="round" strokeLinejoin="round" opacity="0.5" />
        )}
        <polyline points={points(samples, frame)} fill="none" stroke="#e9eff0" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={ax} cy={ay} r="4.5" fill="#e9eff0" />
        <circle cx={bx} cy={by} r="4.5" fill="#e9eff0" />
        <g fontSize="12" fill="#e9eff0" textAnchor="middle">
          <rect x={ax - 28} y={ay + 12} width="56" height="22" rx="11" fill="var(--stage)" stroke="#2c3a3c" />
          <text x={ax} y={ay + 27}>A · 0 m</text>
          <rect x={bx - 32} y={by - 36} width="64" height="22" rx="11" fill="var(--stage)" stroke="#2c3a3c" />
          <text x={bx} y={by - 21}>B · {lineLengthM.toLocaleString("ko-KR", { maximumFractionDigits: 1 })} m</text>
        </g>
        {probe && <circle data-testid="profile-board-probe" cx={px} cy={py} r="7" fill="#e9eff0" stroke="var(--stage)" strokeWidth="2" />}
        <g transform={`translate(${W - 28} 40)`} fill="#8a9699" fontSize="12" textAnchor="middle">
          <path d="M0 14 L0 -4 M-4 2 L0 -4 L4 2" fill="none" stroke="#8a9699" strokeWidth="1.5" />
          <text y="28">북</text>
        </g>
      </svg>
      <p className="border-t px-4 py-3 text-micro" style={{ borderColor: "#2c3a3c", color: "#8a9699" }}>{caption}</p>
    </section>
  );
}
