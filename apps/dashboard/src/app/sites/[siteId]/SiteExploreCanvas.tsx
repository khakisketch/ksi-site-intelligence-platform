import type { WorkArea } from "@/lib/core-api/types";

import { disambiguatedAreaNames, displayName } from "./site-spatial";

export interface ExploreCaptureOption {
  assetRef: string;
  /** 사람용 한 줄 — 종류·실제 촬영 구간·등록 버전(정밀도 그대로). */
  label: string;
  /** 전체 식별 정보 — 파일명·제출 묶음(필요시 구분·상세용). */
  title: string;
  selected: boolean;
}

/**
 * 탐색 첫 화면의 간결한 작업 막대 — 실제 화면(자식)보다 먼저 둔다.
 *
 * - 구역이 하나면 사실 한 줄(선택 상자 없음). 여러 개일 때만 고르는 상자를 둔다.
 * - 촬영 시점은 고르는 상자로 둔다. 선택하면 같은 GET 경로의 정확한
 *   `assetRef`로 돌아오며, 층(정사영상/DSM)은 보기에서 전환한다. 최신 단언·
 *   날짜 추측을 하지 않으며, 날짜만 아는 관측은 '날짜만 확인 · 시각 미상' 그대로 둔다.
 * - 이 막대는 판정·재계산하지 않는다. 호출자가 준 사실을 그대로 옮긴다.
 * - Server Component다. 자식으로 클라이언트 화면을 받는다.
 */
export function SiteExploreCanvas({
  sitePath,
  areas,
  selectedWorkAreaId,
  captureOptions,
  selectedCaption,
  coverageNote,
  children,
}: {
  sitePath: string;
  areas: readonly WorkArea[];
  selectedWorkAreaId: string | null;
  /** 같은 구역 관측들의 정확한 선택지 — 없으면 선택 상자를 두지 않는다. */
  captureOptions: readonly ExploreCaptureOption[];
  /** 선택 중인 관측·층·등록 버전 한 줄 — title hover 없이 그대로 읽힌다. */
  selectedCaption: string | null;
  /** 부분 보기 등 범위 한계 한 줄 — 없으면 null. */
  coverageNote: string | null;
  children: React.ReactNode;
}) {
  const selected = areas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null;
  const names = disambiguatedAreaNames(areas);
  const activeCount = areas.filter((area) => area.status === "ACTIVE").length;
  const selectedOption = captureOptions.find((option) => option.selected) ?? null;
  const selectedName = selected ? (names.get(selected.workAreaId)?.label ?? selected.name) : null;
  // 긴 구역 이름은 두 줄까지만 둔다. 잘린 전체 이름은 같은 자리 펼침에 둔다.
  const showFullName = selectedName !== null && [...selectedName].length > 40;
  return <section aria-label="선택 관측 화면" className="flex flex-col gap-2">
    <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface px-4 py-2.5">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end sm:gap-x-3">
        {areas.length > 1 ? (
          <form method="get" action={sitePath} className="flex w-full min-w-0 flex-1 flex-wrap items-end gap-2 sm:basis-56">
            <div className="min-w-0 flex-1">
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
        ) : selected && selectedName ? (
          <div className="min-w-0 flex-1 sm:basis-56">
            <p className="line-clamp-2 break-words text-[13px] font-semibold">
              작업구역 · {selectedName}
              {selected.status === "ARCHIVED" ? " (보관됨)" : ""}
            </p>
            {showFullName && (
              <details className="text-[12px] text-ink-2">
                <summary className="tap-target cursor-pointer underline decoration-dotted">구역 전체 이름 확인</summary>
                <p className="mt-1 break-words">{selectedName}</p>
              </details>
            )}
          </div>
        ) : (
          <p className="text-[12.5px] text-ink-2" role="status">작업구역을 확인할 수 없습니다. 아래 상세에서 목록을 확인하세요.</p>
        )}
        {captureOptions.length > 0 && selected && (
          <form method="get" action={sitePath} className="flex w-full min-w-0 flex-1 flex-wrap items-end gap-2 sm:basis-64">
            <input type="hidden" name="workAreaId" value={selected.workAreaId} />
            <div className="min-w-0 flex-1">
              <label htmlFor="explore-canvas-capture" className="block text-[12px] font-semibold">촬영 시점</label>
              <select
                id="explore-canvas-capture"
                name="assetRef"
                defaultValue={selectedOption?.assetRef ?? ""}
                className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]"
              >
                {selectedOption === null && <option value="">촬영 시점 선택</option>}
                {captureOptions.map((option) => (
                  <option key={option.assetRef} value={option.assetRef} title={option.title}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" className="btn">보기</button>
          </form>
        )}
      </div>
      {selectedCaption && (
        <p className="break-words text-[12px] leading-5 text-ink-2">선택 중 · {selectedCaption}</p>
      )}
    </div>
    {children}
    {coverageNote && (
      <p className="px-1 text-[12px] leading-5 text-ink-2">{coverageNote}</p>
    )}
  </section>;
}
