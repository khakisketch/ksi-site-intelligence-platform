"use client";

import { useId, useMemo, useState } from "react";
import { coverageCell, decodeAnalysisCoverage, type CoverageGrid, type CoverageState } from "@/lib/analysis-coverage";
import { formatCountKo } from "@/lib/number-format";

const labels: Record<CoverageState, string> = {
  COMMON_VALID: "두 관측 유효", UNAVAILABLE: "자료 없음", MASK_EXCLUDED: "마스크 제외", OUTSIDE: "구역 밖·구멍",
};
const descriptions: Record<CoverageState, string> = {
  COMMON_VALID: "두 관측에서 유효한 값이 있는 계산 셀입니다. 정확도 보증을 뜻하지 않습니다.",
  UNAVAILABLE: "0으로 계산한 셀이 아닙니다. 두 관측의 유효한 값을 함께 확인할 수 없습니다.",
  MASK_EXCLUDED: "등록된 독립 마스크로 계산에서 제외한 셀입니다. 제외 전 물량을 0으로 해석하지 마세요.",
  OUTSIDE: "작업구역의 선택 셀이 아닙니다. 구역 밖 또는 구역의 구멍이며 자료 없음과 다릅니다.",
};

/** Compact row runs draw the exact witness bits, without polygon interpolation or invented imagery. */
function paths(grid: CoverageGrid): Record<CoverageState, string> {
  const parts: Record<CoverageState, string[]> = { COMMON_VALID: [], UNAVAILABLE: [], MASK_EXCLUDED: [], OUTSIDE: [] };
  for (let row = 0; row < grid.rows; row++) {
    let start = 0;
    while (start < grid.columns) {
      const state = coverageCell(grid, row, start);
      let end = start + 1;
      while (end < grid.columns && coverageCell(grid, row, end) === state) end++;
      if (state !== "OUTSIDE") parts[state].push(`M${start} ${row}h${end - start}v1h-${end - start}z`);
      start = end;
    }
  }
  return Object.fromEntries(Object.entries(parts).map(([state, runs]) => [state, runs.join("")])) as Record<CoverageState, string>;
}

function Grid({ grid }: { grid: CoverageGrid }) {
  const id = useId().replaceAll(":", "");
  const geometry = useMemo(() => paths(grid), [grid]);
  const [row, setRow] = useState("1"), [column, setColumn] = useState("1");
  const r = Number(row) - 1, c = Number(column) - 1;
  const valid = row !== "" && column !== "" && Number.isInteger(r) && Number.isInteger(c)
    && r >= 0 && r < grid.rows && c >= 0 && c < grid.columns;
  const state = valid ? coverageCell(grid, r, c) : null;
  const pattern = Math.max(0.05, Math.min(grid.rows, grid.columns) / 24);
  const allStates: CoverageState[] = ["COMMON_VALID", "UNAVAILABLE", "MASK_EXCLUDED", "OUTSIDE"];
  return <figure className="mt-3 min-w-0">
    <svg role="img" aria-label={`계산 범위 격자 · ${formatCountKo(grid.rows)}행 ${formatCountKo(grid.columns)}열. 셀별 상태는 아래 위치 확인에서 읽을 수 있습니다.`}
      viewBox={`0 0 ${grid.columns} ${grid.rows}`} preserveAspectRatio="xMidYMid meet"
      className="h-64 w-full rounded border border-line bg-sunk sm:h-80">
      <defs>
        <pattern id={`${id}-missing`} width={pattern} height={pattern} patternUnits="userSpaceOnUse">
          <rect width={pattern} height={pattern} fill="var(--high-bg)" />
          <path d={`M0 ${pattern}L${pattern} 0`} stroke="var(--high-ink)" strokeWidth={pattern / 3} />
        </pattern>
        <pattern id={`${id}-excluded`} width={pattern} height={pattern} patternUnits="userSpaceOnUse">
          <rect width={pattern} height={pattern} fill="var(--crit-bg)" />
          <circle cx={pattern / 2} cy={pattern / 2} r={pattern / 4} fill="var(--crit-ink)" />
        </pattern>
        {grid.rows * grid.columns <= 64 && <pattern id={`${id}-cells`} width="1" height="1" patternUnits="userSpaceOnUse">
          <path d="M1 0H0V1" fill="none" stroke="var(--surface)" strokeWidth="0.025" />
        </pattern>}
      </defs>
      <path data-coverage-state="COMMON_VALID" d={geometry.COMMON_VALID} fill="var(--mid-ink)" />
      <path data-coverage-state="UNAVAILABLE" d={geometry.UNAVAILABLE} fill={`url(#${id}-missing)`} />
      <path data-coverage-state="MASK_EXCLUDED" d={geometry.MASK_EXCLUDED} fill={`url(#${id}-excluded)`} />
      {grid.rows * grid.columns <= 64 && <rect width={grid.columns} height={grid.rows} fill={`url(#${id}-cells)`} />}
    </svg>
    <figcaption className="mt-2 text-xs leading-5 text-ink-2">
      <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="계산 범위 범례">
        {allStates.filter((item) => item !== "MASK_EXCLUDED" || grid.counts.MASK_EXCLUDED > 0).map((item) => <li key={item} className="flex items-center gap-1.5">
          <svg aria-hidden="true" viewBox={`0 0 ${pattern * 3} ${pattern * 3}`} className="h-3 w-3 border border-line-strong">
            <rect width="100%" height="100%" fill={item === "COMMON_VALID" ? "var(--mid-ink)" : item === "OUTSIDE" ? "var(--sunk)"
              : `url(#${id}-${item === "UNAVAILABLE" ? "missing" : "excluded"})`} />
          </svg>{labels[item]} · {formatCountKo(grid.counts[item])}개
        </li>)}
      </ul>
      <p className="mt-2">기준 관측의 행·열 순서로 그린 계산 격자입니다. 현장 영상이나 배경지도 위의 위치·정확도를 나타내지 않습니다. 색과 무늬는 물량의 크기가 아닌 셀의 사용 상태입니다.</p>
    </figcaption>
    <details className="mt-2 text-xs text-ink-2">
      <summary className="tap-target cursor-pointer font-semibold">셀 위치 확인</summary>
      <div className="mt-2 flex flex-wrap items-end gap-3">
        <label htmlFor={`${id}-row`} className="block">확인할 행
          <input id={`${id}-row`} className="input mt-1 block min-h-11 w-28 text-base" type="number" min={1} max={grid.rows} step={1} value={row} onChange={(e) => setRow(e.target.value)} />
        </label>
        <label htmlFor={`${id}-column`} className="block">확인할 열
          <input id={`${id}-column`} className="input mt-1 block min-h-11 w-28 text-base" type="number" min={1} max={grid.columns} step={1} value={column} onChange={(e) => setColumn(e.target.value)} />
        </label>
      </div>
      <p className="mt-2 leading-5" role="status">{state ? `${labels[state]} — ${descriptions[state]}` : `행은 1–${formatCountKo(grid.rows)}, 열은 1–${formatCountKo(grid.columns)} 사이의 정수로 입력하세요.`}</p>
      {valid && <p className="mt-1 text-ink-muted">기준 격자 행 {formatCountKo(grid.rowOffset + r)} · 열 {formatCountKo(grid.columnOffset + c)} (0부터 시작하는 원본 인덱스)</p>}
    </details>
  </figure>;
}

export function CoverageGridView({ witness }: { witness: unknown }) {
  const grid = useMemo(() => { try { return decodeAnalysisCoverage(witness); } catch { return null; } }, [witness]);
  if (!grid) return <p className="mt-2 text-sm leading-6 text-high-ink">계산 범위 근거를 표시할 수 없습니다. 화면 표시 한도 또는 근거 연결을 확인하세요. 빈 영역이나 0으로 대체하지 않습니다.</p>;
  return <Grid grid={grid} />;
}
