import Link from "next/link";

import { getEvent } from "@/lib/core-api/events";
import { getMission } from "@/lib/core-api/missions";
import { getSite } from "@/lib/core-api/sites";
import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import {
  EVENT_SEVERITY_LABEL,
  EVENT_STATUS_LABEL,
  MISSION_TYPE_LABEL,
  SEVERITY_UNSET_LABEL,
  TRIAGE_STATUS_LABEL,
  humanizeApiError,
  humanizeEventType,
} from "@/lib/core-api/labels";
import { ackSlaMs, ackSlaState, formatElapsed, isUnattended } from "@/lib/core-api/triage";
import { StateBadge, StatusBadge } from "@/components/ui/StatusBadge";
import { ErrorState } from "@/components/ui/ErrorState";
import { EventActions } from "./[eventKey]/EventActions";

// 시안 우측 396px 상세 레일(triage-d-ink-mono.html .detail) 의 실데이터 버전 —
// events/[eventKey]/page.tsx 의 사실 패널과 같은 항목을 보여주되, 그 파일은 건드리지
// 않고 표시 로직만 복제한다(과제 지시). EventActions 는 그대로 import 해 재사용한다.

const dateFormatter = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" });
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateFormatter.format(date);
}

// DwellBar.tsx 의 동명 헬퍼와 같은 반올림 규칙 — export 되어 있지 않아 복제한다.
function formatTargetDuration(ms: number): string {
  if (ms >= DAY) return `${Math.round(ms / DAY)}일`;
  if (ms >= HOUR) return `${Math.round(ms / HOUR)}시간`;
  return `${Math.max(1, Math.round(ms / MINUTE))}분`;
}

// 시안 .fact — 라벨열 고정폭 + 하단 구분선. events/[eventKey]/page.tsx 의 Field 와
// 모양은 같지만 그 파일을 import 하면 서버 전용 모듈 그래프가 불필요하게 얽힌다.
function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[76px_1fr] items-baseline gap-2.5 border-b border-line py-2 last:border-b-0">
      <dt className="text-ink-muted text-xs break-keep">{label}</dt>
      <dd className="text-ink-1 min-w-0 text-[13px] break-token">{value}</dd>
    </div>
  );
}

function PanelShell({ children }: { children: React.ReactNode }) {
  return (
    <aside
      aria-label="선택한 이벤트"
      className="flex max-h-[calc(100vh-2rem)] flex-col overflow-y-auto rounded-lg border border-line bg-surface"
    >
      {children}
    </aside>
  );
}

function CloseLink({ href }: { href: string }) {
  return (
    <Link href={href} className="text-ink-2 tap-target text-xs underline break-keep">
      닫기
    </Link>
  );
}

export async function EventDetailPanel({
  eventKey,
  inCurrentFilter,
  clearHref,
}: {
  /** 미선택이면 빈 상태를 보인다. */
  eventKey: string | undefined;
  /** 선택된 이벤트가 현재 화면의 필터링된 목록에도 있는가 — 딥링크로 들어와 필터
   *  밖의 이벤트를 보고 있을 때 조용히 넘기지 않고 알린다. */
  inCurrentFilter: boolean;
  /** 선택 해제(패널 닫기) 시 갈 곳 — 다른 필터는 보존한 채 `selected` 만 뺀다. */
  clearHref: string;
}) {
  if (!eventKey) {
    return (
      <PanelShell>
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-5 py-16 text-center">
          <h2 className="text-sm font-bold break-keep">왼쪽에서 이벤트를 선택하세요</h2>
          <p className="text-ink-muted text-[12.5px] break-keep">
            목록에서 행을 클릭하면 여기에 상세 정보가 표시됩니다.
          </p>
        </div>
      </PanelShell>
    );
  }

  let event;
  try {
    event = await getEvent(eventKey);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      return (
        <PanelShell>
          <div className="flex flex-col gap-3 px-5 py-6">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-bold break-keep">이벤트를 찾을 수 없음</h2>
              <CloseLink href={clearHref} />
            </div>
            <p className="text-ink-2 text-[12.5px] break-keep">
              선택한 이벤트(<span className="num break-token">{eventKey}</span>)가 삭제되었거나
              잘못된 링크일 수 있습니다.
            </p>
          </div>
        </PanelShell>
      );
    }
    const message =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
    return (
      <PanelShell>
        <div className="flex flex-col gap-3 px-5 py-6">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-bold break-keep">이벤트 상세</h2>
            <CloseLink href={clearHref} />
          </div>
          <ErrorState message={message} />
        </div>
      </PanelShell>
    );
  }

  // 현장·임무 이름, 트리아지 권한은 이벤트 조회와 독립 — 하나가 실패해도 나머지는 보여준다
  // (events/[eventKey]/page.tsx 와 같은 방어 패턴).
  const [siteSettled, missionSettled, whoSettled] = await Promise.allSettled([
    getSite(event.siteId),
    getMission(event.missionId),
    whoAmI(),
  ]);
  const siteName = siteSettled.status === "fulfilled" ? siteSettled.value.name : event.siteId;
  const missionLabel =
    missionSettled.status === "fulfilled"
      ? `${MISSION_TYPE_LABEL[missionSettled.value.missionType]} · ${event.missionId}`
      : event.missionId;
  const canTriage =
    whoSettled.status === "fulfilled" && whoSettled.value.permissions.includes("EVENTS_TRIAGE");

  const severity = event.severity ? EVENT_SEVERITY_LABEL[event.severity] : SEVERITY_UNSET_LABEL;
  // 개수를 세지 않는다 — events/[eventKey]/page.tsx 와 같은 이유(스키마 필드 수 ≠ 증거 개수).
  const hasBundle = Boolean(event.bundle) && Object.keys(event.bundle).length > 0;

  // 방치 시간·확인 SLA — triage.ts 가 정본이다(SLA 값은 여기서 바꾸지 않는다). 서버 렌더
  // 시점의 스냅샷이라 목록의 DwellBar 처럼 실시간으로 째깍이지는 않는다.
  // react-hooks/purity: `Date.now()` 는 렌더 중 호출이 금지된다 — 이 저장소 관례대로
  // (app/page.tsx) `new Date()` + `.getTime()` 을 쓴다.
  const now = new Date();
  const elapsedMs = Math.max(0, now.getTime() - new Date(event.occurredAt).getTime());
  const unattended = isUnattended(event);
  const elapsedText = formatElapsed(elapsedMs, { unattended });
  const slaState = ackSlaState(event, elapsedMs);
  const slaTarget = ackSlaMs(event.severity);

  const fullPageHref = `/events/${encodeURIComponent(event.eventKey)}`;

  return (
    <PanelShell>
      <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-2">
        <Link
          href={fullPageHref}
          className="text-accent-text tap-target text-xs font-medium underline break-keep"
        >
          전체 화면으로 보기
        </Link>
        <CloseLink href={clearHref} />
      </div>

      {!inCurrentFilter && (
        <p className="text-accent-text border-b border-line bg-accent-tint px-4 py-2 text-[12px] break-keep">
          이 이벤트는 현재 필터 결과에는 없습니다 — 딥링크나 이전 선택으로 열람 중입니다.
        </p>
      )}

      <div className="flex flex-col gap-2 border-b border-line px-4 py-3">
        <p className="num text-ink-muted text-[10.5px] font-bold tracking-wide break-token uppercase">
          {event.eventKey}
        </p>
        <h2 className="text-[15px] font-bold break-keep">{humanizeEventType(event.eventType)}</h2>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge label={severity.label} tone={severity.tone} />
          <StatusBadge
            label={EVENT_STATUS_LABEL[event.status].label}
            tone={EVENT_STATUS_LABEL[event.status].tone}
          />
          <StateBadge
            label={TRIAGE_STATUS_LABEL[event.triage].label}
            tone={TRIAGE_STATUS_LABEL[event.triage].tone}
          />
        </div>
      </div>

      {/* 캡처 프레임·바운딩박스·신뢰도는 데이터 경로가 없다 — 그리지 않고 정직한
          자리표시만 둔다(events/[eventKey]/page.tsx 와 동일한 판단). */}
      <div className="border-line-strong bg-sunk mx-4 mt-3 flex items-center justify-center rounded-lg border border-dashed px-4 py-6 text-center">
        <p className="text-ink-muted text-[12px] break-keep">
          {hasBundle
            ? "증거 번들이 수신돼 있습니다 · 캡처 영상 열람 경로 준비 중"
            : "이 사건에 수신된 증거 번들이 없습니다"}
        </p>
      </div>

      <dl className="mx-4 mt-3 flex flex-col rounded-lg border border-line px-3">
        <Fact
          label="현장"
          value={
            <Link href={`/sites/${encodeURIComponent(event.siteId)}`} className="break-token underline">
              {siteName}
            </Link>
          }
        />
        <Fact
          label="임무"
          value={
            <Link
              href={`/missions/${encodeURIComponent(event.missionId)}`}
              className="break-token underline"
            >
              {missionLabel}
            </Link>
          }
        />
        <Fact label="엣지 장치" value={<span className="num break-token">{event.edgeDeviceId}</span>} />
        <Fact label="담당자" value={event.assignee ?? "미배정"} />
        <Fact label="발생 시각" value={<span className="num">{formatDate(event.occurredAt)}</span>} />
        <Fact label="수신 시각" value={<span className="num">{formatDate(event.receivedAt)}</span>} />
        <Fact
          label="최근 충돌 시각"
          value={<span className="num">{formatDate(event.lastConflictAt)}</span>}
        />
        <Fact
          label="확인 경과"
          value={
            <span>
              <span className="num">{elapsedText}</span>
              {unattended && (
                <span
                  className={
                    slaState === "breached"
                      ? "text-crit-ink ml-1.5 font-semibold"
                      : slaState === "due-soon"
                        ? "text-high-ink ml-1.5 font-medium"
                        : "text-ink-muted ml-1.5"
                  }
                >
                  · 목표 {formatTargetDuration(slaTarget)}
                  {slaState === "breached" && " · 확인 목표 초과"}
                  {slaState === "due-soon" && " · 확인 목표 임박"}
                </span>
              )}
            </span>
          }
        />
      </dl>

      {canTriage && (
        <div className="mx-4 my-3">
          <EventActions eventKey={event.eventKey} status={event.status} triage={event.triage} />
        </div>
      )}
    </PanelShell>
  );
}
