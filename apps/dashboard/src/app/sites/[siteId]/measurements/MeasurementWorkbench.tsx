"use client";

import { useState, type FormEvent } from "react";

import { Disclosure } from "@/components/ui/Disclosure";
import { InlineNotice } from "@/components/ui/InlineNotice";
import type { ProfileVerticalReference, SurfaceProfileComparison, SurfaceProfileResult } from "@/lib/core-api/measurement-types";
import { verticalsComparable, verticalText } from "@/lib/measurement-vertical";
import {
  countUnknown,
  crsLabel,
  formatSigned,
  nearestSample,
  readRange,
  unknownLabel,
} from "@/lib/measurement-profile";

import { ProfileBoard } from "./ProfileBoard";
import { ProfileHeightExport } from "./ProfileHeightExport";
import { ProfileChart, type ChartSeries, type DistanceRange, type VerticalRatio } from "./ProfileChart";
import { ProfileComparison } from "./ProfileComparison";

export interface DateOption {
  jobId: string;
  label: string;
  assetRef?: string;
}

export interface LoadedSeries {
  jobId: string;
  label: string;
  result: SurfaceProfileResult;
  /** 이 숫자가 어떤 수직 기준 위에서 읽혔는지. 완료 영수증이 없으면 모른다. */
  vertical?: ProfileVerticalReference | null;
}

export interface UnavailableDate {
  role: "ref" | "cur";
  label: string;
  message: string;
}

export interface WorkbenchProps {
  savedComparison?: SurfaceProfileComparison | null;
  siteId: string;
  workAreaId: string;
  sourceAssetRef?: string;
  featureChooserExternal?: boolean;
  features: { featureId: string; label: string }[];
  selectedFeatureId: string;
  featureName: string;
  featureRevision: number;
  featureLineDigest: string;
  canCompare: boolean;
  canRequest: boolean;
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

function autoSubmit(event: FormEvent<HTMLSelectElement>) {
  event.currentTarget.form?.requestSubmit();
}

export function MeasurementWorkbench(props: WorkbenchProps) {
  const cur = props.current;
  const ref = props.sourceAssetRef && !cur ? null : props.baseline;
  const [ratio, setRatio] = useState<VerticalRatio>("fit");
  const [probeM, setProbeM] = useState<number | null>(null);
  const [range, setRange] = useState<DistanceRange | null>(null);

  if (props.sourceAssetRef && !cur) {
    return (
      <section aria-label="두 시점 높이차" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
        <p className="text-body text-ink-2">선택한 자료의 단면을 먼저 읽으면 다른 날짜와 비교할 수 있습니다.</p>
        {props.unavailable.map((item) => (
          <InlineNotice key={`${item.role}-${item.label}`} tone="high" role="alert" className="mt-3">
            <span className="font-semibold">{item.role === "cur" ? "현재" : "기준"} {item.label}</span> {item.message}
          </InlineNotice>
        ))}
      </section>
    );
  }

  const loaded = [ref, cur].filter((entry): entry is LoadedSeries => entry !== null);
  const sameFeatureRevision = Boolean(ref && cur
    && ref.jobId !== cur.jobId
    && ref.result.feature?.featureId === props.selectedFeatureId
    && cur.result.feature?.featureId === props.selectedFeatureId
    && ref.result.feature.revision === props.featureRevision
    && cur.result.feature.revision === props.featureRevision
    && ref.result.feature.lineDigest === props.featureLineDigest
    && cur.result.feature.lineDigest === props.featureLineDigest
    && ref.result.lineDigest === props.featureLineDigest
    && cur.result.lineDigest === props.featureLineDigest);
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

  // 높이가 선언된 수직 기준 위에서 읽혔거나 두 날짜의 기준이 다르면 그래프 위에서 먼저 말한다.
  const verticalNotices: { key: string; text: string }[] = [];
  if (loaded.some((entry) => verticalText(entry.vertical).kind === "declared")) {
    verticalNotices.push({
      key: "declared",
      text: "높이의 수직 기준은 사용자가 선언한 값이며 파일에서 확인되지 않았습니다. KSI는 선언이 맞는지 검증하지 않습니다. 높이 차와 기울기는 선언한 기준에 따라 의미가 달라질 수 있습니다.",
    });
  }
  if (ref && cur && verticalsComparable(ref.vertical, cur.vertical) === false) {
    verticalNotices.push({
      key: "mismatch",
      text: "두 날짜의 수직 기준이 달라 높이를 서로 빼어 변화로 읽을 수 없습니다. 같은 기준으로 내보낸 자료끼리 비교하세요.",
    });
  }

  const separateTables = !(ref && cur
    && ref.result.samples.length === cur.result.samples.length
    && ref.result.samples.every((row, index) => Math.abs(row.distanceM - cur.result.samples[index]!.distanceM) < 1e-6));

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_404px] lg:grid-rows-[auto_auto] lg:items-start">
      <ProfileBoard
        samples={primary.result.samples}
        lineLengthM={primary.result.lineLengthM}
        probeM={probeM}
        range={range}
        caption="실선이 측정 선입니다. A가 0 m이며, 그래프에서 고른 지점과 구간이 이 선 위에 표시됩니다."
      />

      <aside aria-label="단면" className="min-w-0 self-stretch rounded-xl border border-line bg-surface p-4 sm:p-5 lg:col-start-2 lg:row-start-1 lg:row-span-2">
        <form method="get" className="flex flex-col gap-4">
          <input type="hidden" name="workAreaId" value={props.workAreaId} />
          {props.sourceAssetRef && <input type="hidden" name="assetRef" value={props.sourceAssetRef} />}
          {props.sourceAssetRef && props.curJobId && <input type="hidden" name="cur" value={props.curJobId} />}
          <div>
            {props.features.length > 1 && !props.featureChooserExternal ? (
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
                {props.dateOptions.filter((option) => option.jobId !== props.curJobId
                  && (!props.sourceAssetRef || (option.assetRef && option.assetRef !== props.sourceAssetRef))).map((option) => <option key={option.jobId} value={option.jobId}>{option.label}</option>)}
              </select>
            </label>
            {props.sourceAssetRef ? (
              <div className="flex min-w-0 flex-col gap-1.5 text-micro text-ink-muted">
                <span>현재 · 선택한 자료</span>
                <p className="min-h-10 rounded-md border border-line bg-sunk px-3 py-2 text-caption text-ink-1">
                  {props.dateOptions.find((option) => option.jobId === props.curJobId)?.label ?? "이 자료의 단면을 아직 읽지 않았습니다"}
                </p>
              </div>
            ) : (
              <label className="flex min-w-0 flex-col gap-1.5 text-micro text-ink-muted">현재
                <select name="cur" className="input tabular" defaultValue={props.curJobId ?? ""} onChange={autoSubmit}>
                  {props.dateOptions.map((option) => <option key={option.jobId} value={option.jobId}>{option.label}</option>)}
                </select>
              </label>
            )}
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

        {verticalNotices.map((notice) => (
          <p key={notice.key} role="note" className="mt-3 rounded-lg border border-line bg-sunk px-3 py-2 text-caption leading-5 text-ink-2">{notice.text}</p>
        ))}

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
          <dt className="border-t border-line py-2.5 text-ink-muted">수직 기준</dt>
          <dd className="border-t border-line py-2.5 text-right break-words">
            {loaded.map((entry) => {
              const text = verticalText(entry.vertical);
              return (
                <span key={entry.jobId} className="block">
                  {entry === cur ? "현재" : "기준"} {text.text}
                  {text.kind === "declared" && <span className="block text-micro text-ink-muted">파일에서 확인되지 않은 선언값</span>}
                </span>
              );
            })}
          </dd>
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

        <ProfileHeightExport
          key={JSON.stringify([props.siteId, props.workAreaId, props.selectedFeatureId, props.featureRevision, ref?.jobId, cur?.jobId])}
          siteId={props.siteId}
          workAreaId={props.workAreaId}
          featureId={props.selectedFeatureId}
          baseline={ref}
          current={cur}
        />
      </aside>
      <ProfileComparison
        key={sameFeatureRevision && ref && cur ? `${ref.jobId}:${cur.jobId}:${props.savedComparison?.decisionDigest ?? "none"}` : "no-pair"}
        siteId={props.siteId}
        workAreaId={props.workAreaId}
        feature={{ featureId: props.selectedFeatureId, revision: props.featureRevision, lineDigest: props.featureLineDigest }}
        canCompare={props.canCompare}
        savedComparison={props.savedComparison ?? null}
        canRequest={props.canRequest}
        pair={sameFeatureRevision && ref && cur ? {
          baseline: { jobId: ref.jobId, assetRef: ref.result.assetRef, label: ref.label, spacingM: ref.result.sampleSpacingM, lineLengthM: ref.result.lineLengthM },
          current: { jobId: cur.jobId, assetRef: cur.result.assetRef, label: cur.label, spacingM: cur.result.sampleSpacingM, lineLengthM: cur.result.lineLengthM },
        } : null}
        probeM={probeM}
        onProbe={setProbeM}
      />
    </div>
  );
}
