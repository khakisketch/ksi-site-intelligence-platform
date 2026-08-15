"use client";

import Link from "next/link";
import { useState } from "react";

import { ChangeRegionMap } from "@/components/map/ChangeRegionMap";
import { StateBadge } from "@/components/ui/StatusBadge";
import { formatNetVolumeM3, formatRatioPercent, formatVolumeM3 } from "@/lib/core-api/phase34-labels";
import type { AoiVertex, ChangeRegion, ChangeRegionSetReport } from "@/lib/core-api/types";

/**
 * 변화 영역 목록 + 지도 + "다음 비행 만들기" — 지도와 목록이 같은 선택 상태를
 * 공유한다(지도에서 클릭해도, 목록에서 클릭해도 같은 영역이 뜬다).
 *
 * "다음 비행 만들기"는 여기서 임무를 만들지 않는다 — SurveyWizard로 넘겨
 * 사람이 검토·확정해야 실제로 발급된다(서버 `get_spatial_refresh_draft` 와
 * 같은 원칙: 초안이지 발급이 아니다).
 */
export function ChangeRegionExplorer({
  siteId,
  missionId,
  siteAoi,
  report,
}: {
  siteId: string;
  missionId: string;
  siteAoi: AoiVertex[];
  report: ChangeRegionSetReport;
}) {
  const drawable = report.regions.filter((r) => r.convexHullPolygonWgs84 !== null);
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(
    drawable[0]?.regionId ?? null,
  );
  const selected = report.regions.find((r) => r.regionId === selectedRegionId) ?? null;

  const nextFlightHref = selected
    ? `/sites/${encodeURIComponent(siteId)}/surveys/new` +
      `?purpose=SPATIAL_REFRESH` +
      `&missionId=${encodeURIComponent(missionId)}` +
      `&changeRegionSetId=${encodeURIComponent(report.changeRegionSetId)}` +
      `&regionId=${encodeURIComponent(selected.regionId)}`
    : null;

  return (
    <div className="flex flex-col gap-5 lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-5">
      <ChangeRegionMap
        siteAoi={siteAoi}
        regions={report.regions}
        selectedRegionId={selectedRegionId}
        onSelectRegion={setSelectedRegionId}
      />

      <div className="flex flex-col gap-4">
        {selected && (
          <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <h3 className="text-[13.5px] font-bold break-keep">선택한 영역</h3>
            <dl className="flex flex-col gap-1.5 text-[12.5px]">
              <div className="flex items-baseline justify-between gap-2">
                <dt className="break-keep text-ink-muted">순변화</dt>
                <dd className="num break-token font-semibold">
                  {formatNetVolumeM3(selected.volume.netM3)}
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-2">
                <dt className="break-keep text-ink-muted">절토 · 성토</dt>
                <dd className="num break-token">
                  {formatVolumeM3(selected.volume.cutM3)} · {formatVolumeM3(selected.volume.fillM3)}
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-2">
                <dt className="break-keep text-ink-muted">면적</dt>
                <dd className="num break-token">
                  {selected.volume.areaM2.toLocaleString("ko-KR", { maximumFractionDigits: 0 })} m²
                </dd>
              </div>
              {selected.unmeasurableRatio > 0 && (
                <div className="flex items-baseline justify-between gap-2">
                  <dt className="break-keep text-ink-muted">측정 불가 비율</dt>
                  <dd className="num break-token">{formatRatioPercent(selected.unmeasurableRatio)}</dd>
                </div>
              )}
            </dl>
            {nextFlightHref && (
              <Link href={nextFlightHref} className="btn btn-primary">
                이 영역으로 다음 비행 만들기
              </Link>
            )}
            <p className="text-[11.5px] break-keep text-ink-muted">
              이 영역을 감싸는 범위를 다음 조사의 촬영 범위로 미리 채웁니다. 실제 비행은
              다음 화면에서 사람이 확인하고 확정해야 발급됩니다.
            </p>
          </div>
        )}

        <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[13.5px] font-bold break-keep">
              변화 영역 {report.regions.length}곳
            </h3>
            <StateBadge label="현장 전체 기준" tone="neutral" />
          </div>
          {report.filteredRegionCount > 0 && (
            <p className="text-[11.5px] break-keep text-ink-muted">
              너무 작은 영역 {report.filteredRegionCount}곳은 제외했습니다.
            </p>
          )}
          <ul className="flex flex-col divide-y divide-line">
            {report.regions.map((region) => (
              <RegionRow
                key={region.regionId}
                region={region}
                selected={region.regionId === selectedRegionId}
                onSelect={() =>
                  region.convexHullPolygonWgs84 && setSelectedRegionId(region.regionId)
                }
              />
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function RegionRow({
  region,
  selected,
  onSelect,
}: {
  region: ChangeRegion;
  selected: boolean;
  onSelect: () => void;
}) {
  const disabled = region.convexHullPolygonWgs84 === null;
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        disabled={disabled}
        className={`tap-target -mx-2 flex w-full flex-col gap-0.5 rounded-md px-2 py-2 text-left text-[13px] ${
          disabled
            ? "cursor-not-allowed text-ink-muted"
            : selected
              ? "bg-accent-tint"
              : "hover:bg-sunk"
        }`}
      >
        <span className="flex items-center justify-between gap-2">
          <span className="break-keep font-medium">
            {region.volume.netM3 >= 0 ? "쌓아야 함" : "깎아야 함"}
          </span>
          <span className="num text-[12px] whitespace-nowrap">
            {formatNetVolumeM3(region.volume.netM3)}
          </span>
        </span>
        <span className="text-[11.5px] break-keep text-ink-muted">
          {disabled
            ? `범위를 계산하지 못했습니다${region.aoiDraftUnavailableReason ? ` (${region.aoiDraftUnavailableReason})` : ""}`
            : `${region.volume.areaM2.toLocaleString("ko-KR", { maximumFractionDigits: 0 })} m²`}
        </span>
      </button>
    </li>
  );
}
