import Link from "next/link";

import { formatNetVolumeM3 } from "@/lib/core-api/phase34-labels";

/** 재관측 후보 한 건 — 서버가 계산한 변화 영역 하나를 그대로 옮긴 값이다. */
export interface ReobsSuggestion {
  regionId: string;
  siteId: string;
  siteName: string;
  missionId: string;
  changeRegionSetId: string;
  /** 그 영역의 순변화(㎥). 부호는 이 값 하나로만 말한다(ZoneVolumeDelta 규약). */
  netM3: number;
}

/**
 * 재관측 제안 — 변화 탐지가 집어낸 영역을 다음 비행으로 넘기는 자리(Console v2 §1).
 *
 * **여기서 후보를 만들어 내지 않는다.** 목록은 서버의 변화 영역 추출 결과
 * (`/v1/missions/{id}/region-extraction`)를 그대로 옮긴 것이고, 링크는 이미
 * 있는 폐루프 진입점(`/sites/[siteId]/changes` 의 "다음 비행 만들기")과 **같은
 * 쿼리**로 위저드를 연다 — 같은 행동에 두 개의 경로가 생기면 한쪽만 고쳐지는
 * 날이 온다.
 *
 * 계산이 임무 단위라 홈은 최근 임무 몇 건만 훑는다. 그 범위를 `scopeNote` 로
 * 반드시 밝힌다 — "제안 3건"이 전 현장을 다 본 결과처럼 읽히면 안 된다.
 */
export function ReobsSuggestions({
  items,
  scopeNote,
  canIssueMissions,
}: {
  items: ReobsSuggestion[];
  scopeNote: string;
  /** 임무 발급 권한이 없으면 위저드로 보내지 않는다 — 끝에서만 막히는 링크를 주지 않는다. */
  canIssueMissions: boolean;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-4 py-2.5">
        <h2 className="text-[13.5px] font-bold tracking-tight break-keep">재관측 제안</h2>
        <span className="text-[11.5px] break-keep text-ink-muted">변화 탐지에서 생성됨</span>
      </div>

      {items.length === 0 ? (
        <p className="px-4 py-4 text-[12.5px] break-keep text-ink-2">
          다시 볼 만큼 달라진 곳이 아직 없습니다. {scopeNote}
        </p>
      ) : (
        <>
          <ul className="divide-y divide-line">
            {items.map((item) => {
              const surveyHref =
                `/sites/${encodeURIComponent(item.siteId)}/surveys/new` +
                `?purpose=SPATIAL_REFRESH` +
                `&missionId=${encodeURIComponent(item.missionId)}` +
                `&changeRegionSetId=${encodeURIComponent(item.changeRegionSetId)}` +
                `&regionId=${encodeURIComponent(item.regionId)}`;
              const changesHref =
                `/sites/${encodeURIComponent(item.siteId)}/changes` +
                `?missionId=${encodeURIComponent(item.missionId)}`;

              return (
                <li key={`${item.missionId}:${item.regionId}`} className="flex items-center gap-2.5 px-4 py-2.5">
                  {/* 변화의 방향(쌓임/깎임)은 색이 아니라 부호가 말한다 — 색은 안전
                      상태에만 쓰는 규칙이라 여기서 초록/빨강을 쓰면 위험 신호와 섞인다. */}
                  <span aria-hidden="true" className="h-8 w-[3px] flex-none rounded-sm bg-line-strong" />
                  <Link href={changesHref} className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] font-semibold">{item.siteName}</span>
                    <span className="num block truncate text-[11px] text-ink-muted">
                      순변화 {formatNetVolumeM3(item.netM3)}
                    </span>
                  </Link>
                  {canIssueMissions && (
                    <Link
                      href={surveyHref}
                      className="tap-target inline-flex flex-none items-center rounded-md border border-line-strong bg-surface px-2.5 text-[11.5px] font-semibold whitespace-nowrap transition-colors hover:border-accent hover:bg-accent hover:text-accent-on"
                    >
                      임무 만들기
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="border-t border-line px-4 py-2 text-[11px] break-keep text-ink-muted">{scopeNote}</p>
        </>
      )}
    </section>
  );
}
