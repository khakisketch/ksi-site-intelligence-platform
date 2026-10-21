import type { WorkArea } from "@/lib/core-api/types";

import { disambiguatedAreaNames, displayName } from "./site-spatial";

/**
 * 탐색 첫 화면의 간결한 작업 막대 — 실제 화면(자식)보다 먼저 둔다.
 *
 * - 구역이 하나면 사실 한 줄(선택 상자 없음). 여러 개일 때만 고르는 상자를 둔다.
 * - 보여주는 촬영 시점·층을 한 줄로 밝힌다. 층 전환 버튼은 실제 화면(클라이언트)이 맡는다.
 * - 이 막대는 판정·재계산하지 않는다. 호출자가 준 사실을 그대로 옮긴다.
 * - Server Component다. 자식으로 클라이언트 화면을 받는다.
 */
export function SiteExploreCanvas({
  sitePath,
  areas,
  selectedWorkAreaId,
  captureHeadline,
  layerSummary,
  coverageNote,
  children,
}: {
  sitePath: string;
  areas: readonly WorkArea[];
  selectedWorkAreaId: string | null;
  /** 보여주는 관측의 사람용 한 줄 — 없으면 null(자리가 상태를 말한다). */
  captureHeadline: string | null;
  /** 화면에 올린 층의 사람용 한 줄 — 없으면 null. */
  layerSummary: string | null;
  /** 부분 보기 등 범위 한계 한 줄 — 없으면 null. */
  coverageNote: string | null;
  children: React.ReactNode;
}) {
  const selected = areas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null;
  const names = disambiguatedAreaNames(areas);
  const activeCount = areas.filter((area) => area.status === "ACTIVE").length;
  return <section aria-label="선택 관측 화면" className="flex flex-col gap-2">
    <div className="rounded-lg border border-line bg-surface px-4 py-2.5">
      {areas.length > 1 ? (
        <form method="get" action={sitePath} className="flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1 basis-56">
            <label htmlFor="explore-canvas-area" className="block text-[12px] font-semibold">작업구역</label>
            <select
              id="explore-canvas-area"
              name="workAreaId"
              defaultValue={selected?.workAreaId ?? ""}
              className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]"
            >
              {areas.map((area) => {
                const naming = names.get(area.workAreaId) ?? { label: area.name || area.workAreaId, disambiguated: false };
                return <option key={area.workAreaId} value={area.workAreaId} title={naming.disambiguated ? naming.label : (area.name || area.workAreaId)}>
                  {naming.disambiguated ? naming.label : displayName(naming.label)}{area.status === "ARCHIVED" ? " · 보관됨" : ""}
                </option>;
              })}
            </select>
          </div>
          <button type="submit" className="btn">보기</button>
          {activeCount === 0 && (
            <p className="w-full text-[12px] text-ink-2">고를 수 있는(사용 중) 구역이 없습니다. 보관된 구역의 기록은 그대로 둡니다.</p>
          )}
        </form>
      ) : selected ? (
        <p className="text-[13px] font-semibold break-keep">
          작업구역 · {names.get(selected.workAreaId)?.label ?? selected.name}
          {selected.status === "ARCHIVED" ? " (보관됨)" : ""}
        </p>
      ) : (
        <p className="text-[12.5px] text-ink-2" role="status">작업구역을 확인할 수 없습니다. 아래 상세에서 목록을 확인하세요.</p>
      )}
      {captureHeadline && (
        <p className="mt-1 break-words text-[12.5px] text-ink-1">보여주는 자료 · {captureHeadline}</p>
      )}
      {layerSummary && (
        <p className="mt-0.5 break-words text-[12px] text-ink-2">{layerSummary}</p>
      )}
      {coverageNote && (
        <p className="mt-0.5 break-words text-[12px] text-ink-2">{coverageNote}</p>
      )}
    </div>
    {children}
  </section>;
}
