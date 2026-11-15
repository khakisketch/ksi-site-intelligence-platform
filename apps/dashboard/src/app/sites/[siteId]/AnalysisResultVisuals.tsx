import type { AnalysisCoverageSummary, AnalysisMetrics } from "@/lib/core-api/analysis";
import { Disclosure } from "@/components/ui/Disclosure";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatCountKo, formatNumberKo, formatSignificantKo } from "@/lib/number-format";

/**
 * 체적 표기 — AnalysisRequestPanel의 formatNumber와 같은 규칙(0.1 미만 0 초과
 * 절대값은 유효숫자 3자리, 나머지는 소수 첫째 자리)이라 0.02가 0으로 뭉개지지
 * 않는다. Core가 기록한 값을 옮길 때만 쓰고 새로 계산하지 않는다.
 */
export function formatVolumeM3(value: number): string {
  return Math.abs(value) > 0 && Math.abs(value) < 0.1
    ? formatSignificantKo(value, 3)
    : formatNumberKo(value, 1);
}

function signedVolumeM3(value: number): string {
  const text = formatVolumeM3(value);
  return value > 0 ? `+${text}` : text;
}

/** "10. 25." 형태에서 월·일만 — 차트 축 라벨용. 파싱 불가면 빈 문자열. */
export function shortDateLabel(value: string): string {
  const rendered = formatKoreanDateTime(value, { dateStyle: "medium" });
  const match = /^(\d+)\. (\d+)\. (\d+)\./.exec(rendered);
  return match ? `${match[2]}.${match[3]}` : "";
}

/** 서울 기준 연도 — 파싱 불가면 null. 해가 다른 두 날짜를 짧게 줄여 헷갈리게 하지 않으려는 용도다. */
export function yearOf(value: string): number | null {
  const match = /^(\d+)\./.exec(formatKoreanDateTime(value, { dateStyle: "medium" }));
  return match ? Number(match[1]) : null;
}

/** "2021.10.06 03:30" — 해를 밝혀야 할 때(올해가 아니거나 두 날짜의 해가 다를 때)의 라벨. */
export function fullDateTimeLabel(value: string): string {
  const rendered = formatKoreanDateTime(value, { dateStyle: "medium" });
  const match = /^(\d+)\. (\d+)\. (\d+)\./.exec(rendered);
  if (!match) return "";
  return `${match[1]}.${match[2]}.${match[3]} ${formatKoreanDateTime(value, { timeStyle: "short" })}`;
}

/** 같은 날 촬영이 여럿이라 날짜만으로 구분되지 않을 때 쓰는 "10.25 03:30" 형태 라벨. */
export function shortDateTimeLabel(value: string): string {
  const day = shortDateLabel(value);
  const time = formatKoreanDateTime(value, { timeStyle: "short" });
  return day ? `${day} ${time}` : "";
}

/**
 * 깎임(절토)과 쌓임(성토)을 같은 무게로 나란히 두고, 순변화는 그 차이로 아래에 둔다.
 * 방향을 글로 풀어 쓰지 않는다 — 막대와 부호가 말하고, 크기를 판단하는 말은 쓰지 않는다.
 * 순변화가 0이어도 두 값이 크면 변화가 있었다는 뜻이라, 순변화를 먼저 크게 읽게 하지 않는다.
 * 막대는 두 값 중 큰 쪽을 100%로 둔 이 결과 안의 상대 길이이며 다른 결과와 비교하지 않는다.
 */
export function VolumeBalance({ metrics, compact = false }: { metrics: AnalysisMetrics; compact?: boolean }) {
  const cut = Math.abs(metrics.cutM3);
  const fill = Math.abs(metrics.fillM3);
  const max = Math.max(cut, fill);
  const cutPct = max > 0 ? (cut / max) * 100 : 0;
  const fillPct = max > 0 ? (fill / max) * 100 : 0;
  const valueClass = compact ? "text-lead" : "text-hero";
  return <div className="flex flex-col gap-3">
    <dl className="grid grid-cols-2 gap-4">
      <div>
        <dt className="flex items-center gap-1.5 text-caption text-ink-2">
          <span aria-hidden="true" className="size-2 rounded-sm bg-ink-1" />깎임 <span className="text-ink-muted">절토</span>
        </dt>
        <dd className={`font-mono font-semibold tabular-nums ${valueClass}`}>
          {formatVolumeM3(cut)}<span className="text-body font-normal text-ink-2"> m³</span>
        </dd>
      </div>
      <div className="text-right">
        <dt className="flex items-center justify-end gap-1.5 text-caption text-ink-2">
          <span aria-hidden="true" className="size-2 rounded-sm bg-mid" />쌓임 <span className="text-ink-muted">성토</span>
        </dt>
        <dd className={`font-mono font-semibold tabular-nums ${valueClass}`}>
          {formatVolumeM3(fill)}<span className="text-body font-normal text-ink-2"> m³</span>
        </dd>
      </div>
    </dl>
    <div
      role="img"
      aria-label={`깎임 ${formatVolumeM3(cut)} m³, 쌓임 ${formatVolumeM3(fill)} m³`}
      className="grid h-3 grid-cols-2 gap-0.5"
    >
      <div className="flex justify-end overflow-hidden rounded-l-full bg-sunk">
        <span className="h-full rounded-l-full bg-ink-1" style={{ width: `${cutPct}%` }} />
      </div>
      <div className="flex justify-start overflow-hidden rounded-r-full bg-sunk">
        <span className="h-full rounded-r-full bg-mid" style={{ width: `${fillPct}%` }} />
      </div>
    </div>
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-t border-line pt-2">
      <p className="text-caption text-ink-2">계산상 순변화 <span className="text-ink-muted">성토 − 절토</span></p>
      <p className="font-mono text-lead font-semibold tabular-nums">
        {signedVolumeM3(metrics.netM3)}<span className="text-body font-normal text-ink-2"> m³</span>
      </p>
    </div>
  </div>;
}

/**
 * 불확실성 칩 — 기록 여부를 숫자 바로 아래 한 곳에만 둔다. 기록이 없으면 0이 아니라
 * "미기록"이라고 말하고, 설명은 접힌 상세에 둔다(숫자 옆 문장을 늘리지 않는다).
 */
export function UncertaintyChip({ uncertaintyM3 }: { uncertaintyM3: number | null }) {
  if (uncertaintyM3 === null) {
    return <span className="inline-flex w-fit items-center rounded-md border border-dashed border-high bg-high-bg px-2 py-0.5 text-caption font-semibold text-high-ink">
      불확실성 미기록
    </span>;
  }
  if (typeof uncertaintyM3 !== "number" || !Number.isFinite(uncertaintyM3)) return null;
  return <span className="num inline-flex w-fit items-center rounded-md border border-mid bg-mid-bg px-2 py-0.5 text-caption font-semibold text-mid-ink">
    {`불확실성 ±${formatVolumeM3(uncertaintyM3)} m³ (기록값)`}
  </span>;
}

/** 추이의 한 점 — 날짜 라벨은 계산을 만든 날이 아니라 현재 관측일이다. */
export type TrendPoint = { analysisId: string; sortKey: string; label: string; metrics: AnalysisMetrics };

const TREND_LIMIT = 6;

/**
 * 비교할 수 있는 같은 구역의 결과를 관측일 순으로 나란히 — 위쪽이 쌓임, 아래쪽이 깎임이다.
 * 이번 결과를 진하게 두고 나머지는 연하게 둔다. 모든 막대는 같은 눈금이며 눈금 끝 값을
 * 옆에 적는다. 같은 조건인지는 호출하는 쪽이 확인한 기록만 넘기고, 여기서는 그리기만 한다.
 */
export function ResultTrend({ points, currentId, conditions }: {
  points: TrendPoint[];
  currentId: string | null;
  /** 이 점들이 같은 조건이라고 말할 수 있는 근거 한 줄(구역·임계값·셀 크기). */
  conditions?: string;
}) {
  const sorted = [...points]
    .sort((a, b) => a.sortKey.localeCompare(b.sortKey))
    .slice(-TREND_LIMIT);
  if (sorted.length < 2) {
    return <p className="text-body text-ink-2">비교할 수 있는 이전 결과가 없습니다.</p>;
  }
  const scale = Math.max(
    ...sorted.flatMap((point) => [Math.abs(point.metrics.cutM3), Math.abs(point.metrics.fillM3)]),
  );
  const width = 100;
  const height = 120;
  const mid = height / 2;
  const slot = width / sorted.length;
  const barWidth = Math.min(slot * 0.5, 14);
  const unit = scale > 0 ? (mid - 6) / scale : 0;
  return <figure className="flex flex-col gap-2">
    <div className="flex gap-2">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="h-28 min-w-0 flex-1"
        role="img"
        aria-label={`같은 구역 관측일별 결과 ${sorted.length}건의 깎임과 쌓임 비교`}
      >
        <line x1="0" x2={width} y1={mid} y2={mid} className="stroke-line-strong" strokeWidth="0.6" vectorEffect="non-scaling-stroke" />
        {sorted.map((point, index) => {
          const current = point.analysisId === currentId;
          const x = slot * index + (slot - barWidth) / 2;
          const up = Math.abs(point.metrics.fillM3) * unit;
          const down = Math.abs(point.metrics.cutM3) * unit;
          return <g key={point.analysisId} opacity={current || currentId === null ? 1 : 0.45}>
            <title>{`${point.label} · 깎임 ${formatVolumeM3(Math.abs(point.metrics.cutM3))} m³ · 쌓임 ${formatVolumeM3(Math.abs(point.metrics.fillM3))} m³`}</title>
            <rect x={x} y={mid - up} width={barWidth} height={Math.max(up, 0)} rx="1" className="fill-mid" />
            <rect x={x} y={mid} width={barWidth} height={Math.max(down, 0)} rx="1" className="fill-ink-1" />
          </g>;
        })}
      </svg>
      <div aria-hidden="true" className="flex h-28 w-14 shrink-0 flex-col justify-between text-micro tabular-nums text-ink-muted">
        <span>{formatVolumeM3(scale)} m³</span>
        <span>0</span>
        <span>{formatVolumeM3(scale)} m³</span>
      </div>
    </div>
    <div className="flex pr-16" aria-hidden="true">
      {sorted.map((point) => <span
        key={point.analysisId}
        className={`min-w-0 flex-1 text-center text-micro tabular-nums ${point.analysisId === currentId ? "font-bold text-ink-1" : "text-ink-muted"}`}
      >{point.label}</span>)}
    </div>
    <figcaption className="flex flex-col gap-1 text-caption text-ink-2">
      <span className="flex flex-wrap gap-x-4">
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="size-2 rounded-sm bg-mid" />위 쌓임</span>
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="size-2 rounded-sm bg-ink-1" />아래 깎임</span>
      </span>
      <Disclosure label="비교 조건">
        <p className="mt-1 text-ink-muted">현재 관측일 기준 · {conditions ?? "같은 구역"}</p>
      </Disclosure>
    </figcaption>
    <table className="sr-only">
      <caption>같은 구역 관측일별 깎임과 쌓임(m³)</caption>
      <thead><tr><th scope="col">관측일</th><th scope="col">깎임</th><th scope="col">쌓임</th></tr></thead>
      <tbody>
        {sorted.map((point) => <tr key={point.analysisId}>
          <th scope="row">{point.label}</th>
          <td>{formatVolumeM3(Math.abs(point.metrics.cutM3))} m³</td>
          <td>{formatVolumeM3(Math.abs(point.metrics.fillM3))} m³</td>
        </tr>)}
      </tbody>
    </table>
  </figure>;
}

/**
 * 분석에 쓰인 범위 — 셀 구성만 막대로 보인다. 결과 요약에는 셀 위치(마스크)가 없어
 * 여기서는 그리지 않고, 위치 격자는 기존 계산 범위 보기(AnalysisCoverage)로 연다.
 * 이것은 계산에 쓰인 영역이지 절토·성토가 어디서 났는지 보여주는 변화 지도가 아니다.
 */
export function CoverageStrip({ coverage }: { coverage: AnalysisCoverageSummary }) {
  const selected = coverage.selectedCellCount;
  const used = coverage.commonValidCellCount;
  const usedPct = selected > 0 ? Math.min(100, (used / selected) * 100) : 0;
  const excluded = coverage.thresholdExcludedCellCount + coverage.unavailableCellCount;
  return <div className="flex flex-col gap-3">
    <div
      role="img"
      aria-label={`선택한 ${formatCountKo(selected)}셀 중 ${formatCountKo(used)}셀을 계산에 사용`}
      className="h-3 overflow-hidden rounded-full bg-sunk"
    >
      <span className="block h-full rounded-full bg-ink-2" style={{ width: `${usedPct}%` }} />
    </div>
    <dl className="grid grid-cols-3 gap-3">
      <div><dt className="text-caption text-ink-2">선택 면적</dt><dd className="font-mono text-lead font-semibold tabular-nums">{formatVolumeM3(coverage.selectedAreaM2)} m²</dd></div>
      <div><dt className="text-caption text-ink-2">계산에 쓴 셀</dt><dd className="font-mono text-lead font-semibold tabular-nums">{formatCountKo(used)} / {formatCountKo(selected)}</dd></div>
      <div><dt className="text-caption text-ink-2">제외·계산 불가</dt><dd className="font-mono text-lead font-semibold tabular-nums">{formatCountKo(excluded)}<span className="ml-1 text-caption font-normal text-ink-2">셀</span></dd></div>
    </dl>
  </div>;
}
