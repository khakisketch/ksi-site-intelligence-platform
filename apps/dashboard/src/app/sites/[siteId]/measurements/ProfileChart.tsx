"use client";

import { useRef, useState, type FocusEvent, type KeyboardEvent, type PointerEvent } from "react";

import type { ProfileSample } from "@/lib/core-api/measurement-types";
import { knownRuns, nearestSample, verticalScale } from "@/lib/measurement-profile";

export interface ChartSeries {
  key: "ref" | "cur";
  label: string;
  samples: readonly ProfileSample[];
}

export interface DistanceRange {
  a: number;
  b: number;
}

export type VerticalRatio = "fit" | "true";

const W = 360;
const H = 230;
const LEFT = 40;
const RIGHT = 12;
const TOP = 16;
const BOTTOM = 36;
const PLOT_W = W - LEFT - RIGHT;
const PLOT_H = H - TOP - BOTTOM;

/** 가로축 눈금(m). 선 길이에 맞는 보기 좋은 간격을 고른다. */
function distanceTicks(lengthM: number): number[] {
  const steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
  const step = steps.find((candidate) => lengthM / candidate <= 7) ?? 1000;
  const ticks: number[] = [];
  for (let value = 0; value <= lengthM + 1e-9; value += step) ticks.push(value);
  return ticks;
}

function formatTick(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/**
 * 선을 따른 높이 그래프. 마우스·터치·키보드로 지점을 읽고, 끌어서 구간을 고른다.
 * 모르는 지점에서는 선을 끊는다. 색은 의미 없이 쓰지 않으므로 날짜는 선 모양(점선·실선)으로 가른다.
 */
export function ProfileChart({
  series,
  lengthM,
  ratio,
  probeM,
  onProbe,
  range,
  onRange,
}: {
  series: readonly ChartSeries[];
  lengthM: number;
  ratio: VerticalRatio;
  probeM: number | null;
  onProbe: (distanceM: number | null) => void;
  range: DistanceRange | null;
  onRange: (range: DistanceRange | null) => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ a: number } | null>(null);
  // 키보드로 접근했을 때만 테두리를 보인다. 마우스로 끌 때는 기본 포커스 테두리가 그래프를 가리지 않게 한다.
  const [ring, setRing] = useState(false);
  const primary = series[0]?.samples ?? [];

  const runsBySeries = series.map((item) => ({ item, runs: knownRuns(item.samples) }));
  const scale = verticalScale(runsBySeries.flatMap((entry) => entry.runs), ratio, PLOT_W, PLOT_H, lengthM);
  if (scale === null) {
    return <p className="rounded-md border border-line bg-sunk px-3 py-6 text-center text-body text-ink-2">이 선에서 읽을 수 있는 높이가 없습니다.</p>;
  }

  const xOf = (distanceM: number) => LEFT + (distanceM / lengthM) * PLOT_W;
  const yOf = (value: number) => TOP + (1 - (value - scale.lo) / (scale.hi - scale.lo)) * PLOT_H;
  const baseY = yOf(scale.lo);

  function distanceFromPointer(event: PointerEvent<SVGRectElement>): number {
    const box = svgRef.current!.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    const raw = ((px - LEFT) / PLOT_W) * lengthM;
    const snapped = nearestSample(primary, Math.max(0, Math.min(lengthM, raw)));
    return snapped ? snapped.distanceM : 0;
  }

  function onDown(event: PointerEvent<SVGRectElement>) {
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* 일부 환경은 포인터 캡처를 지원하지 않는다 */ }
    const at = distanceFromPointer(event);
    drag.current = { a: at };
    onRange({ a: at, b: at });
    onProbe(at);
  }
  function onMove(event: PointerEvent<SVGRectElement>) {
    const at = distanceFromPointer(event);
    if (drag.current) onRange({ a: drag.current.a, b: at });
    onProbe(at);
  }
  function onUp() {
    const started = drag.current;
    drag.current = null;
    if (started && range && range.a === range.b) onRange(null);
  }
  function onLeave() {
    if (!drag.current && !range) onProbe(null);
  }
  function onFocus(event: FocusEvent<SVGRectElement>) {
    try { setRing(event.currentTarget.matches(":focus-visible")); } catch { setRing(false); }
  }
  function onKey(event: KeyboardEvent<SVGRectElement>) {
    if (event.key === "Escape") {
      onRange(null);
      onProbe(null);
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const current = probeM === null ? null : nearestSample(primary, probeM);
    const at = current ? current.index : event.key === "ArrowRight" ? -1 : primary.length;
    const nextIndex = Math.max(0, Math.min(primary.length - 1, at + (event.key === "ArrowRight" ? 1 : -1)));
    const next = primary[nextIndex]!.distanceM;
    if (event.shiftKey) onRange({ a: range ? range.a : (current ? current.distanceM : next), b: next });
    else if (range) onRange(null);
    onProbe(next);
  }

  const probes = probeM === null ? [] : runsBySeries.map(({ item }) => ({ item, hit: nearestSample(item.samples, probeM) }));
  const a = range ? Math.min(range.a, range.b) : null;
  const b = range ? Math.max(range.a, range.b) : null;

  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="presentation" className="block h-auto w-full overflow-visible">
      {scale.ticks.map((tick) => (
        <g key={`y${tick}`}>
          <line x1={LEFT} x2={W - RIGHT} y1={yOf(tick)} y2={yOf(tick)} stroke="var(--line)" strokeDasharray="2 3" />
          <text x={LEFT - 6} y={yOf(tick) + 4} textAnchor="end" fontSize="11.5" fill="var(--ink-muted)" className="tabular">{formatTick(tick)}</text>
        </g>
      ))}
      {distanceTicks(lengthM).map((tick) => (
        <text key={`x${tick}`} x={xOf(tick)} y={H - BOTTOM + 18} textAnchor="middle" fontSize="11.5" fill="var(--ink-muted)" className="tabular">{formatTick(tick)}</text>
      ))}
      <text x={W - RIGHT} y={H - 4} textAnchor="end" fontSize="11.5" fill="var(--ink-2)">A에서 거리 (m)</text>
      <text x={LEFT - 30} y={TOP - 7} fontSize="11.5" fill="var(--ink-2)">높이 (m){ratio === "true" ? " · 1:1" : ""}</text>

      {a !== null && b !== null && (
        <rect data-testid="profile-chart-range" x={xOf(a)} y={TOP} width={Math.max(xOf(b) - xOf(a), 1)} height={PLOT_H} fill="var(--accent-tint)" stroke="var(--accent)" strokeWidth="1" />
      )}
      <line x1={LEFT} x2={W - RIGHT} y1={baseY} y2={baseY} stroke="var(--line-strong)" />

      {runsBySeries.map(({ item, runs }) => (
        <g key={item.key} data-series={item.key}>
          {item.key === "cur" && runs.map((run, position) => (
            <path
              key={`area${position}`}
              d={`M${xOf(run[0]!.distanceM)} ${baseY} ${run.map((row) => `L${xOf(row.distanceM)} ${yOf(row.elevationM!)}`).join(" ")} L${xOf(run[run.length - 1]!.distanceM)} ${baseY} Z`}
              fill="var(--sunk)"
              opacity="0.7"
            />
          ))}
          {runs.map((run, position) => (
            <path
              key={`line${position}`}
              d={run.map((row, index) => `${index === 0 ? "M" : "L"}${xOf(row.distanceM).toFixed(1)} ${yOf(row.elevationM!).toFixed(1)}`).join(" ")}
              fill="none"
              stroke={item.key === "cur" ? "var(--ink-1)" : "var(--ink-muted)"}
              strokeWidth={item.key === "cur" ? 2.4 : 1.8}
              strokeDasharray={item.key === "cur" ? undefined : "5 4"}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
        </g>
      ))}

      {probes.map(({ item, hit }) => hit && (
        <g key={`probe${item.key}`}>
          <line x1={xOf(hit.distanceM)} x2={xOf(hit.distanceM)} y1={TOP} y2={baseY} stroke="var(--ink-muted)" strokeDasharray="2 3" />
          {hit.elevationM !== null && (
            <circle cx={xOf(hit.distanceM)} cy={yOf(hit.elevationM)} r="4.5" fill={item.key === "cur" ? "var(--ink-1)" : "var(--ink-muted)"} stroke="var(--surface)" strokeWidth="2" />
          )}
        </g>
      ))}

      {ring && <rect data-testid="profile-chart-focus" x={LEFT - 3} y={TOP - 3} width={PLOT_W + 6} height={PLOT_H + 6} rx="4" fill="none" stroke="var(--accent)" strokeWidth="2" pointerEvents="none" />}
      <rect
        data-testid="profile-chart-hit"
        x={LEFT}
        y={TOP}
        width={PLOT_W}
        height={PLOT_H}
        fill="transparent"
        tabIndex={0}
        role="group"
        aria-label="그래프. 좌우 화살표로 지점을 옮기고 Shift와 함께 누르면 구간을 고릅니다. Esc로 해제합니다."
        style={{ touchAction: "pan-y", cursor: "crosshair", outline: "none" }}
        onFocus={onFocus}
        onBlur={() => setRing(false)}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onLeave}
        onKeyDown={onKey}
      />
    </svg>
  );
}
