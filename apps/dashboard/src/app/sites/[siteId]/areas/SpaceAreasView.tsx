import Link from "next/link";

import { siteAreasHref } from "@/components/nav/site-context";
import { SectionFrame } from "@/components/section/SectionFrame";
import { Disclosure } from "@/components/ui/Disclosure";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { StateBadge } from "@/components/ui/StatusBadge";
import type { WorkArea } from "@/lib/core-api/types";
import { formatKoreanDate } from "@/lib/datetime";
import { WORK_AREA_STATUS_LABEL } from "@/lib/work-areas";

import { disambiguatedAreaNames } from "../site-spatial";
import { SpaceAreasStage } from "./SpaceAreasStage";
import { SpaceViewTabs } from "./SpaceViewTabs";

function AreaRow({ siteId, area, label, current, supersededName }: {
  siteId: string; area: WorkArea; label: string; current: boolean; supersededName: string | null;
}) {
  const archived = area.status !== "ACTIVE";
  return (
    <li>
      <Link
        href={siteAreasHref(siteId, area.workAreaId)}
        aria-current={current ? "true" : undefined}
        className={`tap-target flex min-w-0 flex-col justify-center gap-0.5 rounded-md border px-2.5 py-1.5 hover:bg-sunk ${current ? "border-line-strong bg-sunk" : "border-line"}`}
      >
        <span className={`text-body break-words ${current ? "font-semibold" : "text-ink-2"}`}>{label}</span>
        <span className="text-micro text-ink-muted">
          {formatKoreanDate(area.createdAt)} 등록{supersededName ? ` · 이전 범위(${supersededName})를 대체` : ""}{archived ? " · 보관됨" : ""}
        </span>
      </Link>
    </li>
  );
}

/**
 * 공간의 영역 보기(ADR-KSI-043) — 영역 목록과 지도를 한 화면에 둔다.
 *
 * 이 화면은 읽는 자리다: 영역을 고르고, 지도에서 위치를 확인하고, 그 영역의 자료로 간다.
 * 추가·범위 바꾸기·보관은 영역 관리 보기(`SpaceAreasManage`)가 한다 — 중복 제출 방지·계정 연속성
 * 확인·미확인 제출 복구 같은 안전 장치를 이 화면에 따로 흉내 내지 않는다.
 */
export function SpaceAreasView({ siteId, sitePath, areas, areasState, selectedId, canWrite }: {
  siteId: string;
  sitePath: string;
  areas: readonly WorkArea[];
  areasState: "ready" | "denied" | "unavailable";
  selectedId: string | null;
  canWrite: boolean;
}) {
  const active = areas.filter((area) => area.status === "ACTIVE");
  const archived = areas.filter((area) => area.status !== "ACTIVE");
  // 대체 등록은 이름을 이어받으므로 같은 이름이 흔하다. 사용 중인 영역끼리, 보관된 영역끼리만 구분해
  // 기술 참조가 목록에 끼어들지 않게 한다(사용 중 목록에서는 보통 이름이 하나씩이다).
  const names = new Map([...disambiguatedAreaNames(active), ...disambiguatedAreaNames(archived)]);
  const labelOf = (area: WorkArea) => names.get(area.workAreaId)?.label ?? area.workAreaId;
  const byId = new Map(areas.map((area) => [area.workAreaId, area]));
  const supersededNameOf = (area: WorkArea) => {
    const previous = area.supersedes ? byId.get(area.supersedes) : undefined;
    return previous ? previous.name : null;
  };
  const selected = selectedId ? byId.get(selectedId) ?? null : null;
  // 지도에는 사용 중인 영역과, 보관된 영역을 골랐을 때 그 영역만 올린다.
  const mapAreas = selected && selected.status !== "ACTIVE" ? [...active, selected] : [...active];
  const manageHref = siteAreasHref(siteId, selected?.workAreaId, { manage: true });

  const context = (
    <>
      <SpaceViewTabs sitePath={sitePath} siteId={siteId} workAreaId={selected?.workAreaId ?? null} />
      <section aria-label="영역 목록" className="flex min-w-0 flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2 px-1">
          <h2 className="text-micro font-bold tracking-wide text-ink-muted">영역 {active.length}개</h2>
          {canWrite && active.length > 0 && (
            <Link href={manageHref} className="tap-target hidden items-center text-caption font-semibold underline lg:inline-flex">+ 추가</Link>
          )}
        </div>
        <p className="px-1 text-caption text-ink-2">자료를 붙여 비교하는 영역입니다. 고르면 지도에서 강조됩니다.</p>
        {areasState === "denied" && <InlineNotice tone="high">영역 목록을 조회할 권한이 없습니다. 프로젝트 담당자에게 문의하세요.</InlineNotice>}
        {areasState === "unavailable" && <InlineNotice tone="high">영역 목록을 불러오지 못했습니다. 잠시 후 다시 열어 보세요.</InlineNotice>}
        {areasState === "ready" && areas.length === 0 && (
          <div className="flex flex-col gap-2 rounded-md border border-dashed border-line-strong px-3 py-4">
            <p className="text-body font-bold">등록된 영역이 없습니다</p>
            <p className="text-caption text-ink-2">자료를 등록하고 비교하려면 먼저 대상 영역이 필요합니다.</p>
            {canWrite
              ? <Link href={manageHref} className="btn btn-primary hidden w-fit lg:inline-flex">영역 추가</Link>
              : <p className="text-caption text-ink-muted">영역은 프로젝트 쓰기 권한이 있는 담당자가 등록합니다.</p>}
            {canWrite && <p className="text-caption text-ink-muted lg:hidden">영역 추가는 노트북 이상에서 같은 계정으로 이어서 할 수 있습니다.</p>}
          </div>
        )}
        {active.length > 0 && (
          <ul className="flex flex-col gap-1">
            {active.map((area) => (
              <AreaRow key={area.workAreaId} siteId={siteId} area={area} label={labelOf(area)}
                current={area.workAreaId === selected?.workAreaId} supersededName={supersededNameOf(area)} />
            ))}
          </ul>
        )}
        {archived.length > 0 && (
          <Disclosure label={`보관된 영역 ${archived.length}`} open={archived.some((area) => area.workAreaId === selected?.workAreaId)}>
            <ul className="mt-1 flex flex-col gap-1">
              {archived.map((area) => (
                <AreaRow key={area.workAreaId} siteId={siteId} area={area} label={labelOf(area)}
                  current={area.workAreaId === selected?.workAreaId} supersededName={supersededNameOf(area)} />
              ))}
            </ul>
          </Disclosure>
        )}
      </section>

      {selected && (
        <section aria-label="고른 영역" data-space-area-selected="true" className="flex min-w-0 flex-col gap-2 border-t border-line pt-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2 px-1">
            <h2 className="text-body font-bold break-words">{labelOf(selected)}</h2>
            <StateBadge label={WORK_AREA_STATUS_LABEL[selected.status].label} tone={WORK_AREA_STATUS_LABEL[selected.status].tone} />
          </div>
          <Link
            href={`${sitePath}?workAreaId=${encodeURIComponent(selected.workAreaId)}`}
            className="btn btn-primary"
          >이 영역 자료 보기</Link>
          {canWrite && selected.status === "ACTIVE" && (
            <Link href={manageHref} className="btn hidden lg:inline-flex">범위 바꾸기·보관</Link>
          )}
          {canWrite && selected.status === "ACTIVE" && (
            <p className="px-1 text-caption text-ink-muted lg:hidden">범위 바꾸기·보관은 노트북 이상에서 같은 계정으로 이어서 할 수 있습니다.</p>
          )}
        </section>
      )}
    </>
  );

  return (
    <SectionFrame contextLabel="영역" context={context}>
      <section aria-label="영역 지도" className="flex min-w-0 flex-col gap-2">
        {mapAreas.length > 0
          ? <SpaceAreasStage siteId={siteId} areas={mapAreas} selectedId={selected?.workAreaId ?? ""} />
          : <div className="flex min-h-80 items-center justify-center rounded-lg border border-dashed border-line-strong bg-surface p-6 text-center">
              <p className="text-body text-ink-2">{areas.length === 0 ? "영역을 등록하면 이곳 지도에 그려집니다." : "사용 중인 영역이 없습니다. 보관된 영역은 목록에서 골라 볼 수 있습니다."}</p>
            </div>}
        <p className="px-1 text-caption text-ink-muted">영역 경계는 화면 표시용이며 분석 적합성을 뜻하지 않습니다.</p>
      </section>
    </SectionFrame>
  );
}
