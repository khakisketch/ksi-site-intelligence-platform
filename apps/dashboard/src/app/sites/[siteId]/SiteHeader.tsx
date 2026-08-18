import Link from "next/link";

import { StateBadge } from "@/components/ui/StatusBadge";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { formatKoreanDate } from "@/lib/datetime";
import { SITE_TABS, type SiteEpoch, type SiteTabKey } from "@/lib/site-epochs";
import type { SiteView } from "@/lib/core-api/types";

import { PROCESSING_JOB_STATUS_LABEL } from "@/app/missions/mission-labels";

const EPOCH_DOT: Record<string, string> = {
  SUCCEEDED: "bg-safe",
  RUNNING: "bg-mid",
  QUEUED: "bg-ink-muted",
  FAILED: "bg-crit",
  CANCELLED: "bg-line-strong",
};

const CHIP_DATE = new Intl.DateTimeFormat("ko-KR", {
  month: "numeric",
  day: "numeric",
  timeZone: "Asia/Seoul",
});

/** 링크를 유지한 채 한 파라미터만 바꾼다 — 탭을 옮겨도 고른 시점을 잃지 않는다. */
function hrefWith(
  siteId: string,
  current: { tab?: string; epoch?: string },
  patch: { tab?: string; epoch?: string },
): string {
  const merged = { ...current, ...patch };
  const params = new URLSearchParams();
  if (merged.tab && merged.tab !== "overview") params.set("tab", merged.tab);
  if (merged.epoch) params.set("epoch", merged.epoch);
  const search = params.toString();
  const base = `/sites/${encodeURIComponent(siteId)}`;
  return search ? `${base}?${search}` : base;
}

/**
 * 현장 상세 머리 — 정체(상태·식별자)·행동·시간축·탭이 스크롤 위에 함께 있는 자리.
 *
 * 시안의 "조사 주기" 선택과 "내 현장 고정"은 넣지 않았다. 이 시스템에 조사 주기라는
 * 값은 없고(현장이 가진 것은 모델 노후 판정 기준일 뿐이라 주기로 바꿔 부르면 없는
 * 약속을 만든다), 고정은 저장할 곳이 없어 새로고침하면 사라지는 버튼이 된다.
 */
export function SiteHeader({
  site,
  epochs,
  selectedEpochId,
  tab,
  canStartSurvey,
}: {
  site: SiteView;
  epochs: SiteEpoch[];
  selectedEpochId: string | null;
  tab: SiteTabKey;
  canStartSurvey: boolean;
}) {
  const status = SITE_STATUS_LABEL[site.status];
  const current = { tab, epoch: selectedEpochId ?? undefined };
  const surveyLabel = site.status === "UNMAPPED" ? "베이스라인 임무 발급" : "새 조사";

  return (
    <header className="flex flex-col gap-3 border-b border-line bg-surface px-4 pt-3 sm:px-5">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2">
        {/* topbar 가 '현장 상세'를 이미 찍는다 — 여기 h1 은 대상 이름이라 중복이 아니다. */}
        <h1 className="text-[17px] font-bold tracking-tight break-keep">{site.name}</h1>
        <StateBadge label={status.label} tone={status.tone} />
        <span className="num text-[11.5px] break-token text-ink-muted">{site.siteId}</span>
        <span className="text-[11.5px] break-keep text-ink-2">
          등록 {formatKoreanDate(site.registeredAt)} · 갱신 {formatKoreanDate(site.updatedAt)}
        </span>
        {site.resumeTarget && (
          <span className="text-[11.5px] break-keep text-ink-2">
            복귀 예정 상태 {SITE_STATUS_LABEL[site.resumeTarget].label}
          </span>
        )}

        <span className="ml-auto flex flex-wrap items-center gap-1.5">
          <Link href={`/world?siteId=${encodeURIComponent(site.siteId)}`} className="btn tap-target">
            World에서 보기
          </Link>
          <Link
            href={`/sites/${encodeURIComponent(site.siteId)}/report`}
            className="btn tap-target"
          >
            보고서
          </Link>
          {canStartSurvey ? (
            <Link
              href={`/sites/${encodeURIComponent(site.siteId)}/surveys/new`}
              className="btn btn-primary tap-target"
            >
              {surveyLabel}
            </Link>
          ) : (
            <span className="btn cursor-not-allowed text-ink-muted" aria-disabled="true">
              {surveyLabel}
            </span>
          )}
        </span>
      </div>

      {/* 조사 기록 — 이 현장에서 실제로 돌아간 재구성 시점. 고르면 아래 탭들이 그 시점을
          기준으로 말한다. 성공하지 않은 시점도 남긴다(그 날짜의 결과가 왜 없는지가
          화면에서 사라지면 안 된다, site-epochs.ts). */}
      <div className="flex items-center gap-2 overflow-x-auto pb-0.5">
        <span className="flex-none text-[11px] font-bold break-keep text-ink-muted">조사 기록</span>
        {epochs.length === 0 ? (
          <span className="text-[11.5px] break-keep text-ink-2">
            아직 처리된 조사가 없습니다 — 첫 매핑 비행 뒤 이 줄에 시점이 쌓입니다.
          </span>
        ) : (
          epochs.map((epoch) => {
            const active = epoch.jobId === selectedEpochId;
            const label = PROCESSING_JOB_STATUS_LABEL[epoch.status];
            return (
              <Link
                key={epoch.jobId}
                href={hrefWith(site.siteId, current, { epoch: epoch.jobId })}
                aria-current={active ? "true" : undefined}
                title={`${formatKoreanDate(epoch.issuedAt)} · ${label?.label ?? epoch.status}`}
                className={`num tap-target inline-flex flex-none items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] font-semibold transition-colors ${
                  active
                    ? "border-line-strong bg-sunk"
                    : "border-line bg-surface hover:border-line-strong"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`size-1.5 rounded-full ${EPOCH_DOT[epoch.status] ?? "bg-line-strong"}`}
                />
                {CHIP_DATE.format(new Date(epoch.issuedAt))}
              </Link>
            );
          })
        )}
      </div>

      <nav className="-mb-px flex gap-0.5" aria-label="현장 상세 화면">
        {SITE_TABS.map((option) => {
          const active = option.key === tab;
          return (
            <Link
              key={option.key}
              href={hrefWith(site.siteId, current, { tab: option.key })}
              aria-current={active ? "page" : undefined}
              className={`tap-target inline-flex items-center border-b-2 px-3 text-[13px] break-keep transition-colors ${
                active
                  ? "border-b-ink-1 font-bold"
                  : "border-b-transparent text-ink-2 hover:text-ink-1"
              }`}
            >
              {option.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
