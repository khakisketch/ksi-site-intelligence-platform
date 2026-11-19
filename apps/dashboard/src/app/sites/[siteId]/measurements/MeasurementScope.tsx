"use client";

import Link from "next/link";
import type { ChangeEvent } from "react";

import { siteDataHref } from "@/components/nav/site-context";

type Props = {
  siteId: string;
  areaId?: string;
  areas: { workAreaId: string; name: string; status: string }[];
  lines: { featureId: string; label: string }[];
  featureId?: string;
  source: { assetRef: string; fileName: string; date: string | null } | null;
};

function submitChoice(event: ChangeEvent<HTMLSelectElement>) {
  if (event.currentTarget.value) event.currentTarget.form?.requestSubmit();
}

export function MeasurementScope({ siteId, areaId, areas, lines, featureId, source }: Props) {
  const path = `/sites/${encodeURIComponent(siteId)}/measurements`;
  const areaScope = new URLSearchParams();
  if (areaId) areaScope.set("workAreaId", areaId);
  if (featureId) areaScope.set("feature", featureId);
  return (
    <section aria-label="측정 범위" className="grid min-w-0 gap-3 rounded-lg border border-line bg-surface px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-end gap-3">
        <form action={path} method="get" className="min-w-0 grow sm:max-w-sm">
          <label htmlFor="measurement-work-area" className="grid gap-1 text-caption font-semibold">작업구역
            <select key={areaId ?? ""} id="measurement-work-area" name="workAreaId" className="input min-w-0" defaultValue={areaId ?? ""} required onChange={submitChoice}>
              <option value="" disabled>작업구역을 선택하세요</option>
              {areas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}{area.status === "ARCHIVED" ? " · 보관됨" : ""}</option>)}
            </select>
          </label>
          <noscript><button className="btn" type="submit">구역 선택</button></noscript>
        </form>
        {areaId && lines.length > 1 && <form action={path} method="get" className="min-w-0 grow sm:max-w-sm">
          <input type="hidden" name="workAreaId" value={areaId} />
          {source && <input type="hidden" name="assetRef" value={source.assetRef} />}
          <label htmlFor="measurement-feature" className="grid gap-1 text-caption font-semibold">측정 선
            <select key={featureId} id="measurement-feature" name="feature" className="input min-w-0" defaultValue={featureId} onChange={submitChoice}>
              {lines.map((line) => <option key={line.featureId} value={line.featureId}>{line.label}</option>)}
            </select>
          </label>
          <noscript><button className="btn" type="submit">선 선택</button></noscript>
        </form>}
      </div>
      {areas.length === 0 && <p className="text-body text-ink-2">조회할 작업구역이 없습니다. 현장 담당자에게 작업구역 등록 여부를 확인하세요.</p>}
      {source && areaId && <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line pt-2">
        <div className="min-w-0">
          <p className="text-caption text-ink-muted">선택한 DSM · {source.date ?? "촬영 시기 미상"}</p>
          <p className="break-all text-body font-semibold text-ink-1">{source.fileName}</p>
        </div>
        <div className="flex flex-wrap gap-x-4 text-caption">
          <Link href={siteDataHref(siteId, { workAreaId: areaId, assetRef: source.assetRef })} className="tap-target underline">자료 상세</Link>
          <Link href={`${path}?${areaScope}`} className="tap-target underline">자료 선택 해제</Link>
        </div>
      </div>}
    </section>
  );
}
