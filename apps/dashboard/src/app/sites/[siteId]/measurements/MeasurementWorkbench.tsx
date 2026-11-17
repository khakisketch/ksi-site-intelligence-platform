"use client";

import { useState, type FormEvent } from "react";

import { Disclosure } from "@/components/ui/Disclosure";
import { InlineNotice } from "@/components/ui/InlineNotice";
import type { SurfaceProfileResult } from "@/lib/core-api/measurement-types";
import {
  countUnknown,
  crsLabel,
  formatSigned,
  nearestSample,
  profileCsv,
  readRange,
  unknownLabel,
} from "@/lib/measurement-profile";

import { ProfileBoard } from "./ProfileBoard";
import { ProfileChart, type ChartSeries, type DistanceRange, type VerticalRatio } from "./ProfileChart";

export interface DateOption {
  jobId: string;
  label: string;
}

export interface LoadedSeries {
  jobId: string;
  label: string;
  result: SurfaceProfileResult;
}

export interface UnavailableDate {
  role: "ref" | "cur";
  label: string;
  message: string;
}

export interface WorkbenchProps {
  workAreaId: string;
  features: { featureId: string; label: string }[];
  selectedFeatureId: string;
  featureName: string;
  featureRevision: number;
  dateOptions: DateOption[];
  refJobId: string | null;
  curJobId: string | null;
  baseline: LoadedSeries | null;
  current: LoadedSeries | null;
  unavailable: UnavailableDate[];
  notes: string[];
}

function heightText(row: { elevationM: number | null; invalidReason: Parameters<typeof unknownLabel>[0] | null } | null): string {
  if (!row) return "범위 밖";
  if (row.elevationM === null) return `값 없음 · ${unknownLabel(row.invalidReason!)}`;
  return `${row.elevationM.toFixed(2)} m`;
}

function unknownReasons(result: SurfaceProfileResult): string {
  const counts = countUnknown(result.samples);
  const parts: string[] = [];
  if (counts.edge > 0) parts.push(`가장자리 ${counts.edge}`);
  if (counts.nodata > 0) parts.push(`자료 없음 ${counts.nodata}`);
  if (counts.outside > 0) parts.push(`범위 밖 ${counts.outside}`);
  return parts.join(", ");
}

function downloadCsv(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function autoSubmit(event: FormEvent<HTMLSelectElement>) {
  event.currentTarget.form?.requestSubmit();
}

export function MeasurementWorkbench(props: WorkbenchProps) {
  const { baseline: ref, current: cur } = props;
  const [ratio, setRatio] = useState<VerticalRatio>("fit");
  const [probeM, setProbeM] = useState<number | null>(null);
  const [range, setRange] = useState<DistanceRange | null>(null);

  const loaded = [ref, cur].filter((entry): entry is LoadedSeries => entry !== null);
  const chartSeries: ChartSeries[] = loaded.map((entry) => ({
    key: entry === cur ? "cur" : "ref",
    label: entry.label,
    samples: entry.result.samples,
  }));
  const primary = loaded[0]!;
  const lengthM = Math.max(...loaded.map((entry) => entry.result.lineLengthM));

  function changeRatio(next: VerticalRatio) {
    setRatio(next);
    setRange(null);
  }

  const spanOfRange = range && range.a !== range.b ? range : null;
  const reading = (entry: LoadedSeries) => (spanOfRange ? readRange(entry.result.samples, spanOfRange.a, spanOfRange.b) : null);
  const probeText = probeM === null ? null : chartSeries.map((item) => {
    const hit = nearestSample(item.samples, probeM);
    return `${item.key === "cur" ? "현재" : "기준"} ${heightText(hit)}`;
  }).join(" · ");

  const separateTables = !(ref && cur
    && ref.result.samples.length === cur.result.samples.length
    && ref.result.samples.every((row, index) => Math.abs(row.distanceM - cur.result.samples[index]!.distanceM) < 1e-6));

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_404px] lg:items-start">
      <ProfileBoard
        samples={primary.result.samples}
        lineLengthM={primary.result.lineLengthM}
        probeM={probeM}
        range={range}
        caption="실선이 측정 선입니다. A가 0 m이며, 그래프에서 고른 지점과 구간이 이 선 위에 표시됩니다."
      />

      <aside aria-label="단면" className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5">
        <form method="get" className="flex flex-col gap-4">
          <input type="hidden" name="workAreaId" value={props.workAreaId} />
          <div>
            {props.features.length > 1 ? (
              <label className="flex flex-col gap-1.5 text-micro text-ink-muted">측정 선
                <select name="feature" className="input" defaultValue={props.selectedFeatureId} onChange={autoSubmit}>
                  {props.features.map((feature) => <option key={feature.featureId} value={feature.featureId}>{feature.label}</option>)}
                </select>
              </label>
            ) : <input type="hidden" name="feature" value={props.selectedFeatureId} />}
            <h2 className="mt-4 text-title font-bold tracking-tight break-words">{props.featureName}</h2>
            <p className="mt-0.5 text-caption text-ink-muted">개정 {props.featureRevision}</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex min-w-0 flex-col gap-1.5 text-micro text-ink-muted">기준
              <select name="ref" className="input tabular" defaultValue={props.refJobId ?? ""} onChange={autoSubmit}>
                <option value="">선택 안 함</option>
                {props.dateOptions.map((option) => <option key={option.jobId} value={option.jobId}>{option.label}</option>)}
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1.5 text-micro text-ink-muted">현재
              <select name="cur" className="input tabular" defaultValue={props.curJobId ?? ""} onChange={autoSubmit}>
                {props.dateOptions.map((option) => <option key={option.jobId} value={option.jobId}>{option.label}</option>)}
              </select>
            </label>
          </div>
          <noscript><button type="submit" className="btn">불러오기</button></noscript>
        </form>

        {props.unavailable.map((item) => (
          <InlineNotice key={`${item.role}-${item.label}`} tone="high" role="alert" className="mt-4">
            <span className="font-semibold">{item.role === "cur" ? "현재" : "기준"} {item.label}</span> {item.message}
          </InlineNotice>
        ))}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <ul className="flex flex-wrap gap-1.5" aria-label="표시 중인 날짜">
            {loaded.map((entry) => (
              <li key={entry.jobId} className="tabular inline-flex h-6 items-center gap-2 rounded-full bg-sunk px-2.5 text-caption text-ink-2">
                <span aria-hidden="true" className="inline-block w-4 border-t-2" style={{ borderColor: entry === cur ? "var(--ink-1)" : "var(--ink-muted)", borderTopStyle: entry === cur ? "solid" : "dashed" }} />
                {entry === cur ? "현재" : "기준"} {entry.label}
              </li>
            ))}
          </ul>
          <div role="group" aria-label="세로 비율" className="inline-flex rounded-lg bg-sunk p-0.5">
            {(["fit", "true"] as const).map((mode) => (
              <button key={mode} type="button" aria-pressed={ratio === mode} onClick={() => changeRatio(mode)}
                className={`h-7 rounded-md px-3 text-caption ${ratio === mode ? "bg-surface font-semibold text-ink-1 shadow-sm" : "text-ink-2"}`}>
                {mode === "fit" ? "맞춤" : "1:1"}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-3">
          <ProfileChart series={chartSeries} lengthM={lengthM} ratio={ratio} probeM={probeM} onProbe={setProbeM} range={range} onRange={setRange} />
        </div>

        <div aria-live="polite" className="tabular mt-2 min-h-[3.25rem] text-caption leading-6 text-ink-2">
          {spanOfRange ? (
            <>
              <p><strong className="font-semibold text-ink-1">{Math.min(spanOfRange.a, spanOfRange.b).toFixed(1)}–{Math.max(spanOfRange.a, spanOfRange.b).toFixed(1)} m</strong> 구간 · 길이 {Math.abs(spanOfRange.b - spanOfRange.a).toFixed(1)} m</p>
              <p>
                높이 차(기울기){" "}
                {loaded.map((entry, position) => {
                  const value = reading(entry);
                  return <span key={entry.jobId}>{position > 0 ? " · " : ""}{entry === cur ? "현재" : "기준"} {value ? `${formatSigned(value.heightChangeM, 2)} m (${formatSigned(value.gradePercent, 1)} %)` : "값 부족"}</span>;
                })}
                {" "}<button type="button" className="rounded px-1.5 text-micro text-ink-muted underline" onClick={() => setRange(null)}>해제</button>
              </p>
            </>
          ) : probeText && probeM !== null ? (
            <p>{probeM.toFixed(1)} m · {probeText}</p>
          ) : null}
        </div>

        <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] text-body">
          <dt className="border-t border-line py-2.5 text-ink-muted">선 길이</dt>
          <dd className="tabular border-t border-line py-2.5 text-right">{primary.result.lineLengthM.toFixed(1)} m<span className="block text-micro text-ink-muted">평면 거리</span></dd>
          <dt className="border-t border-line py-2.5 text-ink-muted">좌표계</dt>
          <dd className="border-t border-line py-2.5 text-right break-words">{crsLabel(primary.result.horizontalCrs)}</dd>
          <dt className="border-t border-line py-2.5 text-ink-muted">값 있는 지점</dt>
          <dd className="tabular border-t border-line py-2.5 text-right">{loaded.map((entry, position) => <span key={entry.jobId}>{position > 0 ? " · " : ""}{entry === cur ? "현재" : "기준"} {entry.result.validCount}</span>)}</dd>
          <dt className="border-t border-line py-2.5 text-ink-muted">값 없는 지점</dt>
          <dd className="tabular border-t border-line py-2.5 text-right">
            {loaded.map((entry) => (
              <span key={entry.jobId} className="block">
                {entry === cur ? "현재" : "기준"} {entry.result.unknownCount}
                {entry.result.unknownCount > 0 && <span className="block text-micro text-ink-muted">{unknownReasons(entry.result)}</span>}
              </span>
            ))}
          </dd>
        </dl>

        <Disclosure label="거리별 높이 상세" className="mt-3 border-t border-line pt-2 text-body">
          <div className="mt-2 max-h-64 overflow-auto rounded-lg border border-line">
            {separateTables ? loaded.map((entry) => (
              <table key={entry.jobId} className="tabular w-full border-collapse text-caption">
                <caption className="px-3 py-2 text-left text-micro text-ink-muted">{entry === cur ? "현재" : "기준"} {entry.label}</caption>
                <thead><tr className="text-ink-muted"><th scope="col" className="px-3 py-1.5 text-left font-medium">A에서 거리 (m)</th><th scope="col" className="px-3 py-1.5 text-right font-medium">높이 (m)</th></tr></thead>
                <tbody>{entry.result.samples.map((row) => <tr key={row.index} className="border-t border-line"><td className="px-3 py-1.5">{row.distanceM.toFixed(1)}</td><td className="px-3 py-1.5 text-right">{row.elevationM === null ? <span className="text-ink-muted">값 없음 · {unknownLabel(row.invalidReason!)}</span> : row.elevationM.toFixed(2)}</td></tr>)}</tbody>
              </table>
            )) : (
              <table className="tabular w-full border-collapse text-caption">
                <thead><tr className="text-ink-muted"><th scope="col" className="px-3 py-1.5 text-left font-medium">A에서 거리 (m)</th><th scope="col" className="px-3 py-1.5 text-right font-medium">기준 {ref!.label}</th><th scope="col" className="px-3 py-1.5 text-right font-medium">현재 {cur!.label}</th></tr></thead>
                <tbody>{ref!.result.samples.map((row, index) => {
                  const now = cur!.result.samples[index]!;
                  const cell = (value: typeof row) => value.elevationM === null ? <span className="text-ink-muted">값 없음 · {unknownLabel(value.invalidReason!)}</span> : value.elevationM.toFixed(2);
                  return <tr key={row.index} className="border-t border-line"><td className="px-3 py-1.5">{row.distanceM.toFixed(1)}</td><td className="px-3 py-1.5 text-right">{cell(row)}</td><td className="px-3 py-1.5 text-right">{cell(now)}</td></tr>;
                })}</tbody>
              </table>
            )}
          </div>
        </Disclosure>

        {props.notes.map((note) => <p key={note} className="mt-3 text-micro text-ink-muted">{note}</p>)}
        <p className="mt-3 text-micro text-ink-muted">등록된 격자를 선을 따라 읽은 값입니다. 측량 성과가 아닙니다. 값이 없는 지점은 0 m로 채우지 않습니다.</p>

        <div className="mt-4">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => downloadCsv(`profile-${props.selectedFeatureId.slice(3, 11)}.csv`, profileCsv(loaded.map((entry) => ({ label: `${entry === cur ? "현재" : "기준"} ${entry.label}`, samples: entry.result.samples }))))}
          >CSV 내보내기</button>
        </div>
      </aside>
    </div>
  );
}
