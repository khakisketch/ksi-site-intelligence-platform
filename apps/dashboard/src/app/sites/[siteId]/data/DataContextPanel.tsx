import Link from "next/link";

import { Disclosure } from "@/components/ui/Disclosure";
import { siteDataHref } from "@/components/nav/site-context";
import { dataKindLabel } from "@/lib/operator-language";
import type { WorkArea } from "@/lib/core-api/types";

import { disambiguatedAreaNames } from "../site-spatial";

function AreaLink({ siteId, area, label, current }: { siteId: string; area: WorkArea; label: string; current: boolean }) {
  return (
    <li>
      <Link
        href={siteDataHref(siteId, { workAreaId: area.workAreaId })}
        aria-current={current ? "true" : undefined}
        className={`tap-target flex min-w-0 items-center rounded-md border px-2.5 text-body break-words hover:bg-sunk xl:border-transparent ${current ? "border-line-strong bg-sunk font-semibold" : "border-line text-ink-2"}`}
      >
        {label}
      </Link>
    </li>
  );
}

/**
 * 자료 섹션의 컨텍스트 패널 — 어느 구역의 자료를 볼지, 불러온 자료를 어떻게 좁힐지.
 * 자료 조회가 구역 단위라서 구역 선택이 이 패널의 첫 줄이다. 검색·필터는 이미 불러온 페이지 안에서만 적용된다.
 */
export function DataContextPanel({
  siteId, areas, selectedWorkAreaId, kinds, q, kind, state, cursor, loadedCount, hasMore,
}: {
  siteId: string;
  areas: readonly WorkArea[];
  selectedWorkAreaId: string | null;
  kinds: readonly string[];
  q: string;
  kind: string;
  state: string;
  cursor?: string;
  loadedCount: number | null;
  hasMore: boolean;
}) {
  const names = disambiguatedAreaNames(areas);
  const active = areas.filter((area) => area.status === "ACTIVE");
  const archived = areas.filter((area) => area.status !== "ACTIVE");
  const label = (area: WorkArea) => names.get(area.workAreaId)?.label ?? area.workAreaId;
  const filterProps = { siteId, kinds, q, kind, state, cursor, loadedCount, hasMore };
  return (
    <>
      <section aria-label="작업구역" className="flex min-w-0 flex-col gap-1.5">
        <h2 className="px-1 text-micro font-bold tracking-wide text-ink-muted">작업구역</h2>
        {areas.length === 0 ? (
          <p className="px-1 text-caption text-ink-2">등록된 작업구역이 없습니다.</p>
        ) : (
          <>
            <ul className="flex flex-wrap gap-1 xl:flex-col xl:gap-0.5">
              {active.map((area) => <AreaLink key={area.workAreaId} siteId={siteId} area={area} label={label(area)} current={area.workAreaId === selectedWorkAreaId} />)}
            </ul>
            {archived.length > 0 && (
              <Disclosure label={`보관된 구역 ${archived.length}`} open={archived.some((area) => area.workAreaId === selectedWorkAreaId)}>
                <ul className="mt-1 flex flex-wrap gap-1 xl:flex-col xl:gap-0.5">
                  {archived.map((area) => <AreaLink key={area.workAreaId} siteId={siteId} area={area} label={label(area)} current={area.workAreaId === selectedWorkAreaId} />)}
                </ul>
              </Disclosure>
            )}
          </>
        )}
      </section>

      {selectedWorkAreaId && (
        <>
          <Disclosure label="검색·필터" open={Boolean(q || kind || state)} className="xl:hidden">
            <div className="mt-2"><FilterForm {...filterProps} selectedWorkAreaId={selectedWorkAreaId} /></div>
          </Disclosure>
          <div className="hidden min-w-0 flex-col gap-2 xl:flex">
            <h2 className="px-1 text-micro font-bold tracking-wide text-ink-muted">검색·필터</h2>
            <FilterForm {...filterProps} selectedWorkAreaId={selectedWorkAreaId} />
          </div>
        </>
      )}
    </>
  );
}

type FilterProps = {
  siteId: string;
  selectedWorkAreaId: string;
  kinds: readonly string[];
  q: string;
  kind: string;
  state: string;
  cursor?: string;
  loadedCount: number | null;
  hasMore: boolean;
};

/** 검색·필터 양식 — 좁은 화면은 접힘 안에서 가로로 펴고, 넓은 화면은 왼쪽 열에서 세로로 쌓는다. 같은 GET 양식이다. */
function FilterForm({ siteId, selectedWorkAreaId, kinds, q, kind, state, cursor, loadedCount, hasMore }: FilterProps) {
  return (
    <form action={`/sites/${encodeURIComponent(siteId)}/data`} method="get" className="grid min-w-0 grid-cols-2 gap-2 md:grid-cols-[minmax(0,2fr)_1fr_1fr_auto] md:items-end xl:grid-cols-1 xl:items-stretch" aria-label="자료 조건">
      <input type="hidden" name="workAreaId" value={selectedWorkAreaId} />
      {cursor && <input type="hidden" name="cursor" value={cursor} />}
      <label className="col-span-2 grid gap-1 text-caption font-medium md:col-span-1 xl:col-span-1">자료 검색
        <input name="q" type="search" defaultValue={q} maxLength={80} placeholder="파일명 또는 종류" className="tap-target min-w-0 rounded-md border border-line bg-surface px-2 text-body" />
      </label>
      <label className="grid min-w-0 gap-1 text-caption font-medium">종류
        <select name="kind" defaultValue={kind} className="tap-target min-w-0 rounded-md border border-line bg-surface px-1 text-caption">
          <option value="">모든 종류</option>
          {kinds.map((value) => <option key={value} value={value}>{dataKindLabel(value)}</option>)}
        </select>
      </label>
      <label className="grid min-w-0 gap-1 text-caption font-medium">검사 상태
        <select name="state" defaultValue={state} className="tap-target min-w-0 rounded-md border border-line bg-surface px-1 text-caption">
          <option value="">모든 상태</option>
          <option value="inspected">검사 완료</option>
          <option value="attention">확인 필요</option>
        </select>
      </label>
      <div className="col-span-2 flex flex-wrap items-center gap-2 md:col-span-1 xl:col-span-1">
        <button type="submit" className="btn">적용</button>
        {(q || kind || state) && <Link href={siteDataHref(siteId, { workAreaId: selectedWorkAreaId, cursor })} className="tap-target text-caption underline">초기화</Link>}
      </div>
      {loadedCount !== null && (hasMore || cursor) && <p className="col-span-2 px-1 text-micro text-ink-muted md:col-span-4 xl:col-span-1">이 페이지의 자료 {loadedCount}개에서 검색합니다.</p>}
    </form>
  );
}
