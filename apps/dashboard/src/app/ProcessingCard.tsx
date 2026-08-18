import Link from "next/link";

import { formatKoreanDateTime } from "@/lib/datetime";
import { StatusBadge } from "@/components/ui/StatusBadge";

import { PROCESSING_JOB_STATUS_LABEL } from "./missions/mission-labels";

/** 재구성 작업 한 건 — 서버 목록의 필드를 그대로 옮긴다. */
export interface ProcessingCardItem {
  jobId: string;
  siteId: string;
  siteName: string;
  status: string;
  issuedAt: string;
  detail: string | null;
}

/**
 * 처리 중 · 대기 — 사진을 넘긴 뒤 결과가 나오기까지를 보여주는 자리(Console v2 §1).
 *
 * **진행률 막대도 예상 완료 시각도 그리지 않는다.** 시안에는 둘 다 있지만 이
 * 시스템의 처리 작업은 상태(대기·처리 중·완료·실패·취소)만 보고하고 진행 비율을
 * 내지 않는다 — 없는 숫자를 그럴듯한 막대로 그리면 그건 화면이 지어낸 사실이다
 * (INV-040). 대신 **언제 걸었는지**를 절대 시각으로 남긴다: 30분 전에 건 작업이
 * 아직 '대기 중'인 것과 방금 건 것이 '대기 중'인 것은 전혀 다른 상황이다.
 *
 * 실패는 접어 두지 않는다 — 사유와 함께 그 현장으로 가는 길을 같이 낸다.
 */
export function ProcessingCard({
  items,
  scopeNote,
  unavailableNote,
}: {
  items: ProcessingCardItem[];
  /** 어느 범위를 훑은 결과인지 — 홈은 전 현장을 다 보지 않는다. */
  scopeNote: string;
  /** 조회 자체가 실패했을 때의 사유. 있으면 "없음"이라 말하지 않는다. */
  unavailableNote?: string;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-4 py-2.5">
        <h2 className="text-[13.5px] font-bold tracking-tight break-keep">처리 중 · 대기</h2>
        <span className="ml-auto text-[11px] break-keep text-ink-muted">{scopeNote}</span>
      </div>

      {unavailableNote ? (
        <p className="px-4 py-4 text-[12.5px] break-keep text-ink-2">{unavailableNote}</p>
      ) : items.length === 0 ? (
        <p className="px-4 py-4 text-[12.5px] break-keep text-ink-2">
          기다리고 있는 처리 작업이 없습니다.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((item) => {
            const status = PROCESSING_JOB_STATUS_LABEL[item.status] ?? {
              label: item.status,
              tone: "neutral" as const,
            };
            const failed = item.status === "FAILED";

            return (
              <li key={item.jobId} className="flex flex-col gap-1.5 px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold">
                    {item.siteName}
                  </span>
                  <StatusBadge label={status.label} tone={status.tone} />
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="num min-w-0 flex-1 truncate text-[10.5px] text-ink-muted">
                    {item.jobId}
                  </span>
                  <span className="num flex-none text-[10.5px] whitespace-nowrap text-ink-muted">
                    {formatKoreanDateTime(item.issuedAt, { dateStyle: "medium", timeStyle: "short" })} 요청
                  </span>
                </div>
                {failed && (
                  <div className="flex flex-wrap items-center gap-2 rounded-md bg-crit-bg px-2.5 py-2">
                    <span className="min-w-0 flex-1 text-[11.5px] font-semibold break-keep text-crit-ink">
                      {item.detail ?? "실패 사유가 기록되지 않았습니다."}
                    </span>
                    <Link
                      href={`/sites/${encodeURIComponent(item.siteId)}`}
                      className="tap-target inline-flex flex-none items-center rounded-md border border-accent bg-accent px-2.5 text-[11.5px] font-semibold whitespace-nowrap text-accent-on hover:bg-accent-hover"
                    >
                      현장 열기
                    </Link>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
