import type { WorkArea } from "@/lib/core-api/types";
import Link from "next/link";

import { disambiguatedAreaNames, displayName } from "./site-spatial";
import { SiteSelectionForm } from "./SiteSelectionForm";

export interface ExploreCaptureOption {
  assetRef: string;
  /** 사람용 한 줄 — 종류·실제 촬영 구간·등록 버전(정밀도 그대로). */
  label: string;
  /** 전체 식별 정보 — 파일명·제출 묶음(필요시 구분·상세용). */
  title: string;
  selected: boolean;
}

/**
 * Shared viewer frame: selection rail, mode toolbar, spatial content and optional detail.
 *
 * - 구역이 하나면 사실 한 줄(선택 상자 없음). 여러 개일 때만 고르는 상자를 둔다.
 * - 관측 시점은 고르는 상자로 둔다. 선택하면 같은 GET 경로의 정확한
 *   `assetRef`로 돌아오며, 층(정사영상/DSM)은 같은 레일에서 전환한다. 최신 단언·
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
  compareHref,
  mode = "explore",
  layers,
  toolbar,
  detail,
  observationControls,
  actions,
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
  /** 같은 구역의 두 시점을 나란히 보는 곳으로 가는 주소 — 없으면 두지 않는다. */
  compareHref?: string | null;
  mode?: "explore" | "compare" | "results";
  layers?: React.ReactNode;
  toolbar?: React.ReactNode;
  detail?: React.ReactNode;
  observationControls?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const selected = areas.find((area) => area.workAreaId === selectedWorkAreaId) ?? null;
  const names = disambiguatedAreaNames(areas);
  const activeCount = areas.filter((area) => area.status === "ACTIVE").length;
  const selectedOption = captureOptions.find((option) => option.selected) ?? null;
  const selectedName = selected ? (names.get(selected.workAreaId)?.label ?? selected.name) : null;
  // 긴 구역 이름은 두 줄까지만 둔다. 잘린 전체 이름은 같은 자리 펼침에 둔다.
  const showFullName = selectedName !== null && [...selectedName].length > 40;
  return <section aria-label="선택 관측 화면" className="grid min-w-0 items-start gap-3 lg:grid-cols-[260px_minmax(0,1fr)] xl:has-[>details[open]]:grid-cols-[260px_minmax(0,1fr)_320px]">
    <aside aria-label="공간 보기 선택" className="grid min-w-0 gap-3 rounded-lg border border-line bg-surface p-3 sm:grid-cols-2 lg:sticky lg:top-3 lg:grid-cols-1">
      <div className="flex min-w-0 items-center justify-between gap-2 lg:flex-col lg:items-stretch">
        {areas.length > 1 ? (
          <SiteSelectionForm action={sitePath} className="flex w-full min-w-0 flex-col gap-2">
            {mode !== "explore" && <input type="hidden" name="mode" value={mode} />}
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
            {activeCount === 0 && (
              <p className="w-full text-[12px] text-ink-2">고를 수 있는(사용 중) 구역이 없습니다. 보관된 구역의 기록은 그대로 둡니다.</p>
            )}
          </SiteSelectionForm>
        ) : selected && selectedName ? (
          <div className="min-w-0 flex-1">
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
        <Link href={`${sitePath}/work-areas${selected ? `?workAreaId=${encodeURIComponent(selected.workAreaId)}` : ""}`} className="tap-target w-fit shrink-0 text-[12px] underline">작업구역 관리</Link>
      </div>
      <div className="flex min-w-0 flex-col gap-2">
        {observationControls ?? (mode === "explore" && captureOptions.length > 0 && selected ? (
          <SiteSelectionForm key={selectedOption?.assetRef ?? "unselected"} action={sitePath} className="flex w-full min-w-0 flex-col gap-2">
            <input type="hidden" name="workAreaId" value={selected.workAreaId} />
            <div className="min-w-0 flex-1">
              <label htmlFor="explore-canvas-capture" className="block text-[12px] font-semibold">관측 시점</label>
              <select
                id="explore-canvas-capture"
                name="assetRef"
                defaultValue={selectedOption?.assetRef ?? ""}
                aria-describedby="explore-selection-help"
                className="tap-target mt-1 w-full rounded-md border border-line bg-surface px-2 text-[13px]"
              >
                {selectedOption === null && <option value="">관측 시점 선택</option>}
                {captureOptions.map((option) => (
                  <option key={option.assetRef} value={option.assetRef} title={option.title}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </SiteSelectionForm>
        ) : <div className="text-[12px] text-ink-2"><p className="font-semibold">관측 시점</p><p className="mt-1">{mode === "compare" ? "비교할 관측 목록을 확인하세요." : mode === "results" ? "결과에 연결된 관측과 근거를 확인하세요." : "선택할 관측은 자료·범위 상세에서 확인하세요."}</p></div>)}
      {mode === "explore" && captureOptions.length > 0 && <p id="explore-selection-help" className="sr-only text-[12px] leading-5 text-ink-muted lg:not-sr-only">관측을 선택하면 지도가 바뀝니다.</p>}
      {selectedCaption && (
        <p className="break-words text-[12px] leading-5 text-ink-2">선택 중 · {selectedCaption}</p>
      )}
      {/* 두 시점 보기는 이 화면의 모드 탭에만 있다. 자료를 보다가 "이전
          촬영과 비교"를 직접 찾게 하지 않고, 자료 자리 옆에 둔다. */}
      {compareHref && (
        <p className="text-[12px]">
          <Link href={compareHref} className="tap-target underline">이전 촬영과 비교</Link>
          <span className="sr-only text-ink-muted lg:not-sr-only"> · 같은 구역의 두 시점을 나란히 봅니다</span>
        </p>
      )}
      </div>
      <div className="min-w-0 sm:col-span-2 lg:col-span-1">
        <h3 className="mb-2 text-[12px] font-semibold">표시 레이어</h3>
        {layers ?? <p className="text-[12px] leading-5 text-ink-2">{mode === "compare" ? "두 관측의 레이어는 각 보기에서 확인합니다." : mode === "results" ? "선택한 분석 결과와 연결 자료를 표시합니다." : "표시할 레이어를 확인하지 못했습니다."}</p>}
      </div>
      {actions && <div className="min-w-0 border-t border-line pt-3 sm:col-span-2 lg:col-span-1">{actions}</div>}
    </aside>
    <div aria-label="공간자료 뷰어" className="min-w-0 overflow-hidden rounded-lg border border-line bg-surface lg:col-start-2 lg:row-start-1">
      {toolbar && <div className="border-b border-line bg-surface p-2">{toolbar}</div>}
      <div className="flex min-h-64 min-w-0 flex-col gap-3 p-3 lg:min-h-[60dvh]">{children}</div>
    {coverageNote && (
      <p className="border-t border-line px-3 py-2 text-[12px] leading-5 text-ink-2">{coverageNote}</p>
    )}
    </div>
    {detail && <details data-workspace-detail className="min-w-0 rounded-lg border border-line bg-surface p-2 lg:col-start-2 xl:z-10 xl:row-start-1 xl:mx-2 xl:my-2 xl:justify-self-end xl:open:sticky xl:open:top-3 xl:open:col-start-3 xl:open:mx-0 xl:open:my-0 xl:open:w-full xl:open:p-3">
      <summary className="tap-target cursor-pointer text-[13px] font-semibold">선택 자료 정보</summary>
      <div className="mt-3 flex min-w-0 flex-col gap-3 text-[12px] leading-5 text-ink-2">{detail}</div>
    </details>}
  </section>;
}
