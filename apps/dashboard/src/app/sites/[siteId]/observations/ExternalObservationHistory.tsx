"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { ExternalRelativeVolumeHistoryItem } from "@/lib/core-api/external-result-workflow";
import { formatKoreanDateTime } from "@/lib/datetime";

function number(value: number, digits = 1) {
  return value.toLocaleString("ko-KR", { maximumFractionDigits: digits });
}

function signed(value: number) {
  return `${value > 0 ? "+" : ""}${number(value)} m³`;
}

function compatibilityKey(item: ExternalRelativeVolumeHistoryItem): string | null {
  const result = item.result;
  if (item.state !== "AVAILABLE" || result?.measurementStatus !== "SUCCEEDED" || !result.metrics) return null;
  return [
    result.workAreaId,
    result.zoneDefinitionDigest,
    result.crs,
    result.observedCrsDigest,
    result.verticalReferenceDigest,
    result.executionPolicy.policyDigest,
  ].join("|");
}

function CopyLink({ href }: { href: string }) {
  const [message, setMessage] = useState<string | null>(null);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const copy = async () => {
    const exactUrl = new URL(href, window.location.origin).toString();
    try {
      await navigator.clipboard.writeText(exactUrl);
      setMessage("이 결과 주소를 복사했습니다. 로그인한 권한은 공유되지 않습니다.");
    } catch {
      setFallbackUrl(exactUrl);
      setMessage("주소를 복사하지 못했습니다. 아래 주소를 선택해 복사하세요.");
    }
  };
  return <span className="inline-flex flex-col items-end gap-1"><button className="btn print:hidden" onClick={() => void copy()}>결과 주소 복사</button>{message && <span role="status" className="max-w-72 text-right text-[11.5px] leading-4 text-ink-muted">{message}</span>}{fallbackUrl && <input aria-label="복사할 결과 주소" readOnly className="input w-72 max-w-full text-[11px]" value={fallbackUrl} onFocus={(event) => event.currentTarget.select()} />}</span>;
}

function MetricRow({ item, workAreaName, siteId, detailMode }: {
  item: ExternalRelativeVolumeHistoryItem;
  workAreaName: string | null;
  siteId: string;
  detailMode?: boolean;
}) {
  const result = item.result;
  if (item.state !== "AVAILABLE" || !result) {
    const exactHref = `/sites/${encodeURIComponent(siteId)}/observations/${encodeURIComponent(item.reportRef)}`;
    return (
      <article className="rounded-lg border border-line bg-surface px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[14px] font-semibold">보관 근거 확인 필요</p><p className="mt-1 text-[12px] text-ink-muted">결과 기록 {item.reportRef.slice(-8)}</p></div><div className="flex gap-2"><CopyLink href={exactHref} />{!detailMode && <Link className="btn print:hidden" href={exactHref}>이 결과 열기</Link>}</div></div>
        <p className="mt-1 text-[13px] leading-5 text-ink-2">이 결과는 이력에 남아 있지만 현재 보관 근거를 검증하지 못했습니다. 수치와 비교 차트는 표시하지 않습니다.</p>
      </article>
    );
  }
  const metrics = result.measurementStatus === "SUCCEEDED" ? result.metrics : null;
  const exactHref = `/sites/${encodeURIComponent(siteId)}/observations/${encodeURIComponent(item.reportRef)}`;
  return (
    <article className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <p className="text-[14px] font-bold">{workAreaName ?? "작업구역"} · {formatKoreanDateTime(result.reportedAt, { dateStyle: "medium", timeStyle: "short" })}</p>
          {/* baselineCapturedFrom/To 는 SINGLE_VOLUME 결과에서 null 이다(기준 시기가 없다). 이
              카드는 이 목록 페이지 전용 경로(관측이력, relative-volume-reports 만 반환)로 올 때는
              항상 채워져 있지만, 보고서 상세 페이지([reportRef]/page.tsx)가 병합 조회
              (report_for_site)로 얻은 단일 항목을 그대로 이 컴포넌트에 넘기기도 하므로 null 을
              실제로 만날 수 있다 — 날짜를 지어내지 않고 기준 구간을 생략한다. */}
          <p className="mt-1 text-[12.5px] leading-5 text-ink-2">{result.baselineCapturedFrom !== null && result.baselineCapturedTo !== null ? <>기준 {formatKoreanDateTime(result.baselineCapturedFrom, { dateStyle: "short", timeStyle: "short" })}–{formatKoreanDateTime(result.baselineCapturedTo, { dateStyle: "short", timeStyle: "short" })} → </> : null}현재 {formatKoreanDateTime(result.currentCapturedFrom, { dateStyle: "short", timeStyle: "short" })}–{formatKoreanDateTime(result.currentCapturedTo, { dateStyle: "short", timeStyle: "short" })}</p>
        </div>
        <div className="flex flex-wrap items-start gap-2"><CopyLink href={exactHref} /><Link className="btn print:hidden" href={`/field/work-orders/${encodeURIComponent(result.currentWorkOrderId)}`}>작업 관리</Link><Link className="btn print:hidden" href={`/sites/${encodeURIComponent(siteId)}/observations/new?repeatReportRef=${encodeURIComponent(item.reportRef)}`}>이 범위로 새 관측</Link>{!detailMode && <Link className="btn btn-primary print:hidden" href={exactHref}>상세 보기</Link>}</div>
      </div>
      {metrics ? (
        <div className="overflow-x-auto px-4 py-3"><p className="mb-2 text-[12px] text-ink-muted">{result.reviewedAt ? `결과 검토 ${formatKoreanDateTime(result.reviewedAt, { dateStyle: "short", timeStyle: "short" })}` : "검토 기록 없음"}</p><table className="w-full min-w-[40rem] text-left text-[12.5px]"><thead className="text-ink-muted"><tr><th className="pb-2 pr-4 font-semibold">절토</th><th className="pb-2 pr-4 font-semibold">성토</th><th className="pb-2 pr-4 font-semibold">순변화</th><th className="pb-2 pr-4 font-semibold">공통 유효 영역</th><th className="pb-2 font-semibold">불확실성</th></tr></thead><tbody><tr className="border-t border-line"><td className="num py-2 pr-4 text-[17px] font-bold">{number(metrics.cutM3)} m³</td><td className="num py-2 pr-4 text-[17px] font-bold">{number(metrics.fillM3)} m³</td><td className="num py-2 pr-4 text-[17px] font-bold">{signed(metrics.netM3)}</td><td className="py-2 pr-4">{number(metrics.commonValidFraction * 100)}%<span className="block text-[11px] text-ink-muted">{number(metrics.measuredAreaM2)} / {number(metrics.zoneAreaM2)} m²</span></td><td className="py-2">{metrics.uncertaintyM3 === null ? "미산정" : `±${number(metrics.uncertaintyM3)} m³`}<span className="block text-[11px] leading-4 text-ink-muted">{metrics.uncertaintyNote}</span></td></tr></tbody></table></div>
      ) : <p className="px-4 py-3 text-[13px] leading-5 text-ink-2">비교 결과 수치를 표시할 수 없습니다.</p>}
    </article>
  );
}

function NetTrend({ items, workAreaNames }: { items: readonly ExternalRelativeVolumeHistoryItem[]; workAreaNames: ReadonlyMap<string, string> }) {
  const groups = useMemo(() => {
    const output = new Map<string, ExternalRelativeVolumeHistoryItem[]>();
    for (const item of items) {
      const key = compatibilityKey(item);
      if (key === null) continue;
      output.set(key, [...(output.get(key) ?? []), item]);
    }
    return [...output.values()];
  }, [items]);
  if (groups.length === 0) return null;
  return <section className="rounded-lg border border-line bg-surface px-4 py-3">
    <h2 className="text-[15px] font-bold">호환되는 비교의 순변화</h2>
    <p className="mt-1 text-[12.5px] leading-5 text-ink-2">같은 구역·구역 정의·좌표·수직 기준·정책이 모두 일치한 결과만 같은 줄에 표시합니다. 누적 합계나 공간 분포를 만들지 않습니다.</p>
    <div className="mt-3 space-y-4">
      {groups.map((group, groupIndex) => {
        const chronological = group.toSorted((left, right) => (
          left.result!.currentCapturedTo.localeCompare(right.result!.currentCapturedTo)
        ));
        const max = Math.max(...group.map((item) => Math.abs(item.result?.metrics?.netM3 ?? 0)), 1);
        const first = chronological[0]!.result!;
        return <div key={compatibilityKey(group[0]!)} className="space-y-2">
          <p className="text-[12px] font-semibold text-ink-2">{workAreaNames.get(first.workAreaId) ?? "작업구역"} · 호환 비교 {groupIndex + 1} <span className="font-normal text-ink-muted">(이 묶음의 표시 범위 ±{number(max)} m³)</span></p>
          {chronological.map((item) => {
            const result = item.result!;
            const net = result.metrics!.netM3;
            return <div key={item.reportRef} className="grid grid-cols-[8rem_minmax(0,1fr)_4.5rem] items-center gap-2 text-[12px]">
              <span>{formatKoreanDateTime(result.currentCapturedTo, { dateStyle: "short" })}</span>
              <span className="h-3 overflow-hidden rounded bg-sunk">{net !== 0 && <span className={`block h-full ${net < 0 ? "bg-high" : "bg-accent"}`} style={{ width: `${(Math.abs(net) / max) * 100}%` }} />}</span>
              <span className="num text-right">{signed(net)}</span>
            </div>;
          })}
        </div>;
      })}
    </div>
  </section>;
}

export function ExternalObservationHistory({
  siteId,
  items,
  workAreaNames,
  detailMode = false,
}: {
  siteId: string;
  items: readonly ExternalRelativeVolumeHistoryItem[];
  workAreaNames: ReadonlyMap<string, string>;
  detailMode?: boolean;
}) {
  return <div className="flex flex-col gap-4">
    <NetTrend items={items} workAreaNames={workAreaNames} />
    <section className="flex flex-col gap-3">
      {items.map((item) => <MetricRow key={item.reportRef} item={item} siteId={siteId} detailMode={detailMode} workAreaName={item.result ? workAreaNames.get(item.result.workAreaId) ?? null : null} />)}
      {items.length === 0 && <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px] text-ink-2">아직 보관된 외부 비교 결과가 없습니다.</p>}
    </section>
  </div>;
}
