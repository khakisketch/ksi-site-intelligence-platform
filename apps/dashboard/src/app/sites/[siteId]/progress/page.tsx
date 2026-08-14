import Link from "next/link";
import { notFound } from "next/navigation";

import { CoreApiError } from "@/lib/core-api/client";
import { getDesignProgress } from "@/lib/core-api/design";
import { DESIGN_SURFACE_STATUS_LABEL, humanizeApiError } from "@/lib/core-api/labels";
import { listDesignSurfaces } from "@/lib/core-api/design";
import { getSite } from "@/lib/core-api/sites";
import { ErrorState } from "@/components/ui/ErrorState";
import { DiffHeatmapOverlay } from "@/components/map/DiffHeatmapOverlay";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatNetVolumeM3, formatVolumeM3 } from "@/lib/core-api/phase34-labels";
import type { DesignSurface, ZoneProgress } from "@/lib/core-api/types";

/**
 * 계획 대비 진척(M4-C) — "계획한 만큼 지금 몇 %까지 됐나".
 *
 * 이 화면은 **저장된 값을 보여주지 않는다.** 사람이 지정한 원지형 기준 리포트와
 * 최신 리포트를 서버가 그 자리에서 빼서 만든 표를 그대로 옮긴다(`getDesignProgress`
 * 참조). 그래서 표를 못 내는 이유(기준 미지정·설계면 판 불일치·문턱 불일치 등)가
 * "데이터 없음"과 다른 사실로 화면에 나온다 — 둘을 뭉개면 사용자가 무엇을 해야
 * 진척이 나오는지 알 수 없다.
 */

function ProgressBar({ ratio }: { ratio: number | null }) {
  if (ratio === null) {
    return <span className="text-[12px] break-keep text-ink-muted">해당 없음</span>;
  }
  const clamped = Math.max(0, Math.min(1, ratio));
  const overshoot = ratio > 1 || ratio < 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-full max-w-40 overflow-hidden rounded-full bg-sunk">
        <div
          className={overshoot ? "h-full bg-crit-ink" : "h-full bg-accent-text"}
          style={{ width: `${Math.round(clamped * 100)}%` }}
        />
      </div>
      <span className="num text-[12.5px] font-semibold whitespace-nowrap">
        {(ratio * 100).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%
      </span>
    </div>
  );
}

function ZoneProgressRow({ zone }: { zone: ZoneProgress }) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
      <span className="text-[13px] font-bold break-keep">
        {zone.zoneName ?? zone.zoneId}
      </span>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <p className="text-[11.5px] break-keep text-ink-muted">절토(깎기)</p>
          <p className="text-[12.5px] break-keep text-ink-2">
            계획 {formatVolumeM3(zone.plannedCutM3)} · 완료{" "}
            {formatNetVolumeM3(zone.doneCutM3)} · 잔여 {formatVolumeM3(zone.remainingCutM3)}
          </p>
          <ProgressBar ratio={zone.cutProgressRatio} />
        </div>
        <div className="flex flex-col gap-1">
          <p className="text-[11.5px] break-keep text-ink-muted">성토(쌓기)</p>
          <p className="text-[12.5px] break-keep text-ink-2">
            계획 {formatVolumeM3(zone.plannedFillM3)} · 완료{" "}
            {formatNetVolumeM3(zone.doneFillM3)} · 잔여 {formatVolumeM3(zone.remainingFillM3)}
          </p>
          <ProgressBar ratio={zone.fillProgressRatio} />
        </div>
      </div>
      <p className="text-[12px] break-keep text-ink-muted">{zone.basis}</p>
    </li>
  );
}

function SurfacePicker({ siteId, surfaces }: { siteId: string; surfaces: DesignSurface[] }) {
  if (surfaces.length === 0) {
    return (
      <p className="text-[12.5px] break-keep text-ink-muted">
        이 현장에는 등록된 설계 기준면이 없습니다.{" "}
        <Link
          href={`/sites/${encodeURIComponent(siteId)}/design`}
          className="tap-target inline-flex items-center font-semibold text-accent-text hover:underline"
        >
          설계 기준면 올리기
        </Link>
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-2">
      {surfaces.map((surface) => (
        <li key={surface.designSurfaceId}>
          <Link
            href={`/sites/${encodeURIComponent(siteId)}/progress?designSurfaceId=${encodeURIComponent(surface.designSurfaceId)}`}
            className="tap-target flex flex-col gap-1 rounded-lg border border-line bg-surface p-3 text-[12.5px] transition-colors hover:bg-sunk"
          >
            <span className="font-semibold break-keep text-accent-text">
              {surface.name} · {surface.revision}
            </span>
            <span className="text-[11.5px] break-keep text-ink-2">
              {DESIGN_SURFACE_STATUS_LABEL[surface.status].label} · {surface.verifiedAt ? `검증 ${formatKoreanDateTime(surface.verifiedAt, { dateStyle: "medium", timeStyle: "short" })}` : `등록 ${formatKoreanDateTime(surface.registeredAt, { dateStyle: "medium", timeStyle: "short" })}`}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default async function SiteProgressPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ designSurfaceId?: string }>;
}) {
  const { siteId } = await params;
  const { designSurfaceId } = await searchParams;

  let site;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    const message =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState message={message} />
      </div>
    );
  }

  const header = (
    <div className="flex flex-col gap-1">
      <Link
        href={`/sites/${encodeURIComponent(site.siteId)}`}
        className="text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
      >
        ← {site.name}
      </Link>
      <h2 className="break-keep text-[19px] font-bold tracking-tight">계획 대비 진척</h2>
      <p className="max-w-2xl text-[12.5px] break-keep text-ink-2">
        시공 전 지형을 기준으로 계획한 절토·성토량 중, 지금까지 얼마를 끝냈고 얼마가
        남았는지를 구역별로 보여줍니다. 흙 물량만 셉니다 — 구조물·포장 공정은 여기
        들어가지 않습니다.
      </p>
    </div>
  );

  if (!designSurfaceId) {
    const surfaces = await listDesignSurfaces(site.siteId)
      .then((r) => r.surfaces)
      .catch(() => [] as DesignSurface[]);
    return (
      <div className="flex flex-col gap-5 p-4 sm:p-5">
        {header}
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
            어느 설계 기준면 대비 진척을 볼까요?
          </h3>
          <SurfacePicker siteId={site.siteId} surfaces={surfaces} />
        </section>
      </div>
    );
  }

  let progressResponse;
  try {
    progressResponse = await getDesignProgress(site.siteId, designSurfaceId);
  } catch (error) {
    const message =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        {header}
        <ErrorState message={message} />
      </div>
    );
  }

  const { progress, unmatchedZoneIds, areaMismatchZoneIds, detail, latestMissionId } =
    progressResponse;

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      {header}

      {progress === null ? (
        <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
          <p className="text-[12.5px] break-keep text-ink-2">
            {detail ?? "진척을 계산할 수 없습니다."}
          </p>
          <p className="text-[12.5px] break-keep text-ink-muted">
            원지형 기준 지정은 그 임무의 설계 대비 잔량 결과 화면에서{" "}
            <span className="font-semibold">&ldquo;이 리포트를 원지형 기준으로
            지정&rdquo;</span>
            버튼으로 합니다.
          </p>
        </section>
      ) : (
        <>
          <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
                구역별 진척
              </h3>
              <span className="text-[11.5px] break-keep text-ink-muted">
                문턱 {progress.thresholdM} m 미만 차이는 집계에서 뺐습니다
              </span>
            </div>
            <p className="rounded-md border border-line bg-sunk px-2.5 py-2 text-[12px] break-keep text-ink-2">
              기준(원지형) {formatKoreanDateTime(progress.baselineComputedAt)} → 최신{" "}
              {formatKoreanDateTime(progress.latestComputedAt)}. 기준 시점이 이미 일부 시공된
              뒤였다면 계획이 실제보다 적게 잡힙니다 — 기준을 다시 확인하세요. 이 진척은
              정산·기성 근거가 아닙니다(설계면은 측정물이 아니라 검증된 오차한계가
              없습니다).
            </p>
            {unmatchedZoneIds.length > 0 && (
              <p className="text-[12px] break-keep text-ink-muted">
                이번 표에서 뺀 구역 {unmatchedZoneIds.length}건(기준 또는 최신 한쪽에만
                있었습니다): {unmatchedZoneIds.join(", ")}
              </p>
            )}
            {areaMismatchZoneIds.length > 0 && (
              <p className="text-[12px] break-keep text-ink-muted">
                이번 표에서 뺀 구역 {areaMismatchZoneIds.length}건(zoneId는 같지만 측정
                면적이 기준 시점과 크게 달라 같은 곳을 쟀다고 볼 수 없었습니다 — 즉석으로
                그린 구역이 매번 다른 범위였거나, 이번 비행에서 일부가 안 찍혔을 수
                있습니다): {areaMismatchZoneIds.join(", ")}
              </p>
            )}
            <ul className="flex flex-col gap-2">
              {progress.zones.map((zone) => (
                <ZoneProgressRow key={zone.zoneId} zone={zone} />
              ))}
            </ul>
            <Link
              href={`/sites/${encodeURIComponent(site.siteId)}/report?designSurfaceId=${encodeURIComponent(designSurfaceId)}`}
              className="text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
            >
              현장 보고서 내보내기 →
            </Link>
          </section>

          {latestMissionId && (
            <DiffHeatmapOverlay
              missionId={latestMissionId}
              designConformanceId={progress.latestDesignConformanceId}
              thresholdM={progress.thresholdM}
            />
          )}
        </>
      )}
    </div>
  );
}
