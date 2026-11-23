import Link from "next/link";
import type { ReactNode } from "react";

import { siteDataHref } from "@/components/nav/site-context";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { Disclosure } from "@/components/ui/Disclosure";
import { EmptyState } from "@/components/ui/EmptyState";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { Tone } from "@/lib/core-api/labels";
import type { WorkArea } from "@/lib/core-api/types";
import { koreanCalendarDate } from "@/lib/observation-default-name";
import { WORK_AREA_STATUS_LABEL, partitionWorkAreas } from "@/lib/work-areas";

import { WorkbenchRefreshButton } from "../WorkbenchMediaState";
import { disambiguatedAreaNames, selectableGeometry } from "../site-spatial";
import {
  approxAreaSquareMeters,
  areaVertexCount,
  assignAreaMarks,
  formatApproxArea,
  layoutCaptureStrip,
  shortDate,
  summarizeAreaAssets,
  type AreaAssetSummary,
  type AreaAssetsInput,
  type AreaMark,
} from "./area-summary";
import { SiteAreasMap } from "./SiteAreasMap";

export type { AreaAssetsInput } from "./area-summary";

/**
 * 공간 화면 왼쪽 패널의 "영역" 탭 — 영역 목록, 고른 영역 상세, 지도 강조를 한 곳에서 보는 읽기 중심 화면이다.
 *
 * - 영역별 자료 요약(건수·최근일·좌표계)은 Core에 없다. 지금은 **고른 영역의 카탈로그 한 페이지(최근 50건)**만
 *   읽으므로 요약은 고른 영역에만 보이고, 고르지 않은 영역에는 자료 건수·좌표계 칩을 두지 않는다(지어내지 않는다).
 * - 편집(이름 바꾸기·범위 다시 그리기·보관)은 기존 `/work-areas` 화면으로 가는 링크 하나다. 임시 저장·결과 불명
 *   처리가 그 화면에 있어 이 탭은 쓰기를 하지 않는다.
 * - 보관은 읽기 전용이다. 보관을 되돌리는 API가 없어 해제 단추를 두지 않는다.
 * - 체적 비교는 항상 열린 것처럼 보이지 않게 잠금으로 보인다. 열림 여부는 분석 화면과 Core가 판정한다.
 */

type Props = {
  siteId: string;
  sitePath: string;
  areas: readonly WorkArea[];
  areasState: "ready" | "denied" | "unavailable";
  /** 영역 등록·편집(SITES_WRITE) 권한. unknown은 확인하지 못한 상태다. */
  canWrite: "allowed" | "denied" | "unknown";
  selectedWorkAreaId: string | null;
  /** 고른 영역의 자료 읽기 결과. */
  assets: AreaAssetsInput;
};

const NO_AREA_REASON_DENIED = "영역 등록 권한이 없습니다. 현장 담당자에게 문의하세요.";
const NO_AREA_REASON_UNKNOWN = "영역 등록 권한을 확인하지 못했습니다.";
const COMPACT_REASON = "영역 그리기와 편집은 노트북에서 같은 계정으로 이어서 하세요.";

/** 보관된 영역을 다른 영역이 대체했는가 — `supersedes`는 새 영역이 이전 영역을 가리킨다. */
function isReplaced(areas: readonly WorkArea[], area: WorkArea): boolean {
  return areas.some((other) => other.supersedes === area.workAreaId);
}

/** 등록일(MM-DD, 한국 달력). 읽을 수 없으면 null. */
function registeredDate(createdAt: string): string | null {
  const moment = new Date(createdAt);
  return Number.isNaN(moment.getTime()) ? null : shortDate(koreanCalendarDate(moment));
}

function areasHref(sitePath: string, workAreaId: string): string {
  return `${sitePath}?panel=areas&workAreaId=${encodeURIComponent(workAreaId)}`;
}

function Swatch({ mark, size = "list" }: { mark: AreaMark | null; size?: "list" | "head" }) {
  const color = mark ? `var(--crs-${mark.swatch})` : "var(--idle)";
  if (size === "head") return <span aria-hidden="true" className="size-3.5 shrink-0 rounded-[4px]" style={{ background: color }} />;
  return (
    <span className="mt-0.5 grid size-[22px] shrink-0 place-items-center rounded-md text-micro font-bold text-white" style={{ background: color }}>
      {mark ? mark.ordinal : "·"}
    </span>
  );
}

function Fact({ children, tone }: { children: ReactNode; tone?: Tone }) {
  const color = tone === "positive" ? "bg-safe-bg text-safe-ink"
    : tone === "caution" ? "bg-high-bg text-high-ink"
    : "bg-sunk text-ink-2";
  return <li className={`inline-flex min-h-[22px] items-center rounded-md px-2 text-caption break-keep ${color}`}>{children}</li>;
}

/** 고른 영역의 자료 한 줄 요약 — 읽지 못한 것을 0건으로 단정하지 않는다. */
function AssetsLine({ assets, summary }: { assets: AreaAssetsInput; summary: AreaAssetSummary | null }) {
  if (assets.status === "denied") return <span className="text-caption text-ink-2">자료 목록을 확인하지 못했습니다 · 조회 권한이 없습니다.</span>;
  if (assets.status === "unavailable") return <span className="text-caption text-ink-2">자료 목록을 확인하지 못했습니다.</span>;
  if (!summary) return null;
  return (
    <>
      <span className="text-caption text-ink-2">
        자료 {summary.count}건{summary.latestDate ? ` · 최근 ${shortDate(summary.latestDate)}` : ""}
        {summary.truncated && <span className="text-ink-muted"> · 최근 50건 기준</span>}
      </span>
      <StatusBadge label={summary.crs.label} tone={summary.crs.tone} />
    </>
  );
}

function CaptureStrip({ dates }: { dates: readonly string[] }) {
  const strip = layoutCaptureStrip(dates);
  if (!strip) return null;
  return (
    <svg role="img" aria-label={`자료 날짜: ${strip.spoken}`} viewBox="0 0 300 34" className="block h-auto w-full">
      <line x1={4} y1={12} x2={296} y2={12} strokeWidth={2} strokeLinecap="round" className="stroke-line-strong" />
      {strip.points.map((point) => (
        <g key={point.date}>
          {point.latest
            ? <circle cx={point.x} cy={12} r={6} strokeWidth={2.5} className="fill-surface stroke-ink-1" />
            : <circle cx={point.x} cy={12} r={5} className="fill-ink-1" />}
          <text x={point.x} y={30} fontSize={10} textAnchor="middle" fontWeight={point.latest ? 700 : 400} className={point.latest ? "fill-ink-1" : "fill-ink-muted"}>
            {shortDate(point.date)}
          </text>
        </g>
      ))}
    </svg>
  );
}

function ShortcutLink({ href, children, locked = false }: { href: string; children: ReactNode; locked?: boolean }) {
  return (
    <Link
      href={href}
      className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border px-2 text-caption font-semibold break-keep ${locked ? "border-line bg-sunk text-ink-2" : "border-line-strong bg-surface text-ink-1"}`}
    >
      {children}
    </Link>
  );
}

function SelectedDetail({
  area, label, mark, props, summary,
}: {
  area: WorkArea;
  label: string;
  mark: AreaMark | null;
  props: Props;
  summary: AreaAssetSummary | null;
}) {
  const { siteId, sitePath, canWrite, assets } = props;
  const active = area.status === "ACTIVE";
  const status = WORK_AREA_STATUS_LABEL[area.status];
  const geometry = selectableGeometry(area);
  const areaText = formatApproxArea(approxAreaSquareMeters(geometry?.polygon, geometry?.crs));
  const vertices = areaVertexCount(area);
  const dataHref = siteDataHref(siteId, { workAreaId: area.workAreaId });
  const analysisHref = `${sitePath}/analysis?workAreaId=${encodeURIComponent(area.workAreaId)}`;
  const editHref = `${sitePath}/work-areas?workAreaId=${encodeURIComponent(area.workAreaId)}`;
  const dateCount = summary?.captureDates.length ?? 0;
  const replaced = isReplaced(props.areas, area);

  return (
    <section aria-label="고른 영역" data-areas-detail={area.workAreaId} className="flex min-w-0 flex-col gap-3 border-t border-line pt-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Swatch mark={mark} size="head" />
        <h4 className="min-w-0 break-words text-title font-semibold">{label}</h4>
        <StatusBadge label={status.label} tone={status.tone} />
      </div>

      {!active && (
        <div className="flex flex-col gap-1 rounded-md bg-sunk px-3 py-2 text-caption break-keep text-ink-2">
          <p>삭제가 아니라 보관입니다. 이미 낸 결과는 그대로 남고, 새 비교에서는 고를 수 없습니다.</p>
          {replaced && <p>새 범위로 대체되었습니다.</p>}
        </div>
      )}

      <ul aria-label="영역 사실" className="flex flex-wrap gap-1.5">
        {areaText && <Fact>{areaText}</Fact>}
        {vertices !== null && <Fact>꼭짓점 {vertices}개</Fact>}
        <Fact>구역 {area.crs}</Fact>
        {summary && (
          summary.crs.kind === "none"
            ? <Fact>자료 좌표계 확인 전</Fact>
            : <Fact tone={summary.crs.tone === "neutral" ? undefined : summary.crs.tone}>자료 {summary.crs.codes.join(" · ")}</Fact>
        )}
      </ul>

      {summary?.crs.kind === "mixed" && (
        <InlineNotice tone="high" role="note">
          좌표계가 다른 자료가 섞여 있습니다. 같은 좌표계 자료끼리만 비교할 수 있으며, 가능 여부는 분석 화면에서 확인합니다.
        </InlineNotice>
      )}

      {summary && summary.crs.kind !== "none" && (summary.crsBasis.measured < summary.crsBasis.dsm || summary.truncated) && (
        <p data-crs-basis className="text-micro break-keep text-ink-muted">
          좌표계는 검사가 끝난 DSM {summary.crsBasis.measured}건{summary.crsBasis.measured < summary.crsBasis.dsm ? `(DSM ${summary.crsBasis.dsm}건 중)` : ""} 기준입니다{summary.truncated ? " · 최근 50건만 읽었습니다" : ""}.
        </p>
      )}

      <div className="flex min-w-0 flex-col gap-1">
        {summary ? (
          <>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-caption font-semibold">이 영역 자료 {summary.count}건</span>
              <span className="text-micro text-ink-muted">
                {dateCount > 0 ? `날짜 ${dateCount}개${dateCount > 8 ? " · 최근 8개 표시" : ""}` : "촬영일 정보 없음"}
              </span>
            </div>
            <CaptureStrip dates={summary.captureDates} />
          </>
        ) : (
          <span className="text-caption font-semibold">이 영역 자료</span>
        )}
        {assets.status !== "ready" && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {assets.status === "not-requested"
              ? <span className="text-caption text-ink-2">자료 요약을 불러오지 않았습니다.</span>
              : <AssetsLine assets={assets} summary={null} />}
            {assets.status === "unavailable" && <WorkbenchRefreshButton />}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Link href={dataHref} className="btn btn-primary w-full justify-center">
          {active ? "이 영역 자료 보기" : "지난 자료 보기"}
        </Link>
        {active && (
          <>
            <div className="grid grid-cols-2 gap-2">
              {canWrite === "allowed"
                ? <ShortcutLink href={`${sitePath}/measurements/new?workAreaId=${encodeURIComponent(area.workAreaId)}`}>선 단면 그리기</ShortcutLink>
                : <ShortcutLink href={`${sitePath}/measurements?workAreaId=${encodeURIComponent(area.workAreaId)}`}>측정 선 보기</ShortcutLink>}
              <ShortcutLink href={analysisHref} locked>
                <svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>
                체적 비교
              </ShortcutLink>
            </div>
            <p data-volume-compare-lock className="rounded-md bg-high-bg px-2 py-1.5 text-micro break-keep text-high-ink">
              체적 비교는 기본 잠김입니다. 두 날짜의 독립 근거와 호환성 승인이 있어야 열립니다. 열림 여부는{" "}
              <Link href={analysisHref} className="font-semibold underline">분석 화면</Link>에서 확인합니다.
            </p>
          </>
        )}
      </div>

      {active && canWrite === "allowed" && (
        <ResponsiveActionBoundary action="SITE_DEVICE_TRANSITION" inlineNotice={false} reason={COMPACT_REASON}>
          <div className="flex flex-col gap-1 border-t border-line pt-2">
            <Link href={editHref} data-area-edit className="btn btn-quiet btn-sm w-fit">영역 편집</Link>
            <p className="text-micro break-keep text-ink-muted">이름 바꾸기와 범위 다시 그리기는 같은 모양의 새 영역을 등록하고 이전 영역을 보관합니다.</p>
          </div>
        </ResponsiveActionBoundary>
      )}
    </section>
  );
}

export function SiteAreasPanel(props: Props) {
  const { sitePath, areas, areasState, canWrite, selectedWorkAreaId, assets } = props;

  if (areasState === "denied") {
    return <InlineNotice tone="high" role="alert">영역 목록을 조회할 권한이 없습니다. 현장 담당자에게 문의하세요.</InlineNotice>;
  }
  if (areasState === "unavailable") {
    return (
      <InlineNotice tone="high" role="alert" action={<WorkbenchRefreshButton label="영역 목록 다시 불러오기" />}>
        영역 목록을 불러오지 못했습니다.
      </InlineNotice>
    );
  }

  const { active, archived } = partitionWorkAreas(areas);
  if (active.length === 0 && archived.length === 0) {
    return (
      <div data-areas-panel="empty">
        <EmptyState
          compact
          title="아직 영역이 없습니다"
          description="영역을 그리면 자료를 영역별로 모아 비교합니다."
          action={canWrite === "allowed"
            ? { label: "첫 영역 그리기", href: `${sitePath}/work-areas`, responsiveAction: "SITE_DEVICE_TRANSITION", compactReason: COMPACT_REASON }
            : undefined}
          blockedReason={canWrite === "denied" ? NO_AREA_REASON_DENIED : canWrite === "unknown" ? NO_AREA_REASON_UNKNOWN : undefined}
        />
      </div>
    );
  }

  const marks = assignAreaMarks(active);
  const names = disambiguatedAreaNames(areas);
  const selected = areas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null;
  const summary = selected && assets.status === "ready" ? summarizeAreaAssets(assets.assets, assets.hasMore) : null;
  const nameOf = (area: WorkArea) => names.get(area.workAreaId)?.label ?? area.workAreaId;

  return (
    <div data-areas-panel="ready" className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-col gap-1 lg:hidden">
        <SiteAreasMap areas={areas} selectedWorkAreaId={selectedWorkAreaId} variant="mini" />
        <p className="text-micro break-keep text-ink-muted">영역 경계는 화면 표시용이며 분석 적합성을 뜻하지 않습니다.</p>
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <h4 className="text-micro font-bold tracking-wide text-ink-muted">사용 중 영역 {active.length}개</h4>
        {canWrite === "allowed" && (
          <div className="ml-auto flex min-w-0 flex-col items-end">
            <ResponsiveActionBoundary action="SITE_DEVICE_TRANSITION" title="노트북에서 이어서 하기" reason={COMPACT_REASON}>
              <Link href={`${sitePath}/work-areas`} data-area-draw className="btn btn-primary btn-sm">영역 그리기</Link>
            </ResponsiveActionBoundary>
          </div>
        )}
      </div>
      {canWrite !== "allowed" && (
        <p data-areas-readonly className="text-micro break-keep text-ink-muted">
          {canWrite === "denied" ? "보기만 가능 · 편집은 담당자에게 요청" : "편집 권한을 확인하지 못해 보기만 가능합니다."}
        </p>
      )}

      {active.length > 0 ? (
        <ul aria-label="사용 중 영역" className="flex flex-col gap-1">
          {active.map((area) => {
            const isSelected = area.workAreaId === selectedWorkAreaId;
            const geometry = selectableGeometry(area);
            const areaText = formatApproxArea(approxAreaSquareMeters(geometry?.polygon, geometry?.crs));
            return (
              <li key={area.workAreaId}>
                <Link
                  href={areasHref(sitePath, area.workAreaId)}
                  aria-current={isSelected ? "true" : undefined}
                  className={`flex gap-2.5 rounded-lg border px-2.5 py-2 ${isSelected ? "border-line-strong bg-sunk" : "border-transparent hover:bg-sunk"}`}
                >
                  <Swatch mark={marks.get(area.workAreaId) ?? null} />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="flex items-baseline gap-2">
                      <span className={`min-w-0 break-words text-lead ${isSelected ? "font-semibold" : "font-medium"}`}>{nameOf(area)}</span>
                      {areaText && <span className="ml-auto shrink-0 text-caption text-ink-2">{areaText}</span>}
                    </span>
                    {/* Core 추가 필요: 영역별 요약 { assetCount, latestCaptureDate, captureDates[], dataCrsState }.
                        지금은 영역마다 카탈로그를 따로 읽어야 해서 고른 영역에만 자료 요약을 보인다. */}
                    {isSelected && (
                      <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                        <AssetsLine assets={assets} summary={summary} />
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-caption break-keep text-ink-2">사용 중인 영역이 없습니다. 보관된 영역만 있습니다.</p>
      )}

      {archived.length > 0 && (
        <Disclosure label={`보관된 영역 ${archived.length}개`} data-areas-archived summaryClassName="text-caption text-ink-2">
          <div className="flex flex-col gap-2 pt-1">
            <p className="text-micro break-keep text-ink-muted">삭제 아님 · 이미 낸 결과 유지. 새 비교에서는 고를 수 없습니다.</p>
            <ul aria-label="보관된 영역" className="flex flex-col gap-1">
              {archived.map((area) => {
                const isSelected = area.workAreaId === selectedWorkAreaId;
                return (
                  <li key={area.workAreaId}>
                    <Link
                      href={areasHref(sitePath, area.workAreaId)}
                      aria-current={isSelected ? "true" : undefined}
                      className={`flex flex-col gap-0.5 rounded-lg border px-2.5 py-2 ${isSelected ? "border-line-strong bg-sunk" : "border-transparent hover:bg-sunk"}`}
                    >
                      <span className="flex items-baseline gap-2">
                        <span className="min-w-0 break-words text-body text-ink-2">{nameOf(area)}</span>
                        <StatusBadge label={WORK_AREA_STATUS_LABEL.ARCHIVED.label} tone={WORK_AREA_STATUS_LABEL.ARCHIVED.tone} />
                      </span>
                      <span className="text-micro text-ink-muted">
                        {registeredDate(area.createdAt) ? `${registeredDate(area.createdAt)} 등록` : "등록일 확인 불가"}{isReplaced(areas, area) ? " · 새 범위로 대체" : ""}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        </Disclosure>
      )}

      {selected && (
        <SelectedDetail
          area={selected}
          label={nameOf(selected)}
          mark={marks.get(selected.workAreaId) ?? null}
          props={props}
          summary={summary}
        />
      )}
    </div>
  );
}
