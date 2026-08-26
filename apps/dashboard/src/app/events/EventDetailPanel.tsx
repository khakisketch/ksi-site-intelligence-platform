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
import { StateBadge, StatusBadge } from "@/components/ui/StatusBadge";
import { ErrorState } from "@/components/ui/ErrorState";
import { EventActions } from "./[eventKey]/EventActions";
import { EvidencePanel } from "./[eventKey]/EvidencePanel";
import { AckElapsedFact } from "./AckElapsedFact";
import { formatKoreanDateTime } from "@/lib/datetime";

// 시안 우측 396px 상세 레일(triage-d-ink-mono.html .detail) 의 실데이터 버전 —
// events/[eventKey]/page.tsx 의 사실 패널과 같은 항목을 보여준다. EventActions 와
// EvidencePanel 은 그대로 import 해 재사용한다.
//
// 2026-08-17: 처음에는 EvidencePanel 이 재사용 목록에서 빠져 자리표시만 그렸고, 그
// 결과 같은 증거를 두고 이 화면만 아직 열어볼 수 없다고 말했다 — 경로는 이미 있었다.
// 표시 로직을 복제하면 반드시 갈라진다. 이 파일은 async 서버 컴포넌트이고 EvidencePanel
// 은 "use client" 이지만, 서버 컴포넌트가 client 컴포넌트를 import 하는 것은 정상 경로다
// (EventActions 를 같은 이유로 이미 그렇게 쓰고 있다).
// 이 주석에 옛 자리표시 문구를 그대로 옮겨 적지 말 것 — evidence-panel-wiring.test.ts
// 가 그 문자열의 부재로 회귀를 잡는다.

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return formatKoreanDateTime(value, { dateStyle: "medium", timeStyle: "short" });
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
      aria-label="선택한 확인 항목"
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
          <h2 className="text-sm font-bold break-keep">왼쪽에서 확인 항목을 선택하세요</h2>
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
              <h2 className="text-sm font-bold break-keep">확인 항목을 찾을 수 없음</h2>
              <CloseLink href={clearHref} />
            </div>
            <p className="text-ink-2 text-[12.5px] break-keep">
              선택한 확인 항목이 삭제되었거나
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
            <h2 className="text-sm font-bold break-keep">확인 항목 상세</h2>
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

  // "확인 경과" Fact 의 초기값 — AckElapsedFact(client) 가 마운트 후 60초마다 실제
  // 경과로 갈아탈 때까지 보여줄 서버 렌더 시점 스냅샷이다. SLA 판정·텍스트 조합은
  // triage.ts 가 정본이고, 그 계산은 AckElapsedFact 안에 있다(여기서 중복하지 않는다).
  // react-hooks/purity: `Date.now()` 는 렌더 중 호출이 금지된다 — 이 저장소 관례대로
  // (app/page.tsx) `new Date()` + `.getTime()` 을 쓴다.
  const now = new Date();
  const initialElapsedMs = Math.max(0, now.getTime() - new Date(event.occurredAt).getTime());

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
          이 확인 항목은 현재 필터 결과에는 없습니다 — 이전 링크로 열람 중입니다.
        </p>
      )}

      <div className="flex flex-col gap-2 border-b border-line px-4 py-3">
        <p className="text-ink-muted text-[11.5px] font-bold break-keep">{siteName}</p>
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

      {/* 증거는 전체 화면(events/[eventKey]/page.tsx)과 **같은 컴포넌트를 그대로** 쓴다 —
          같은 사건의 같은 사실을 두 화면이 다르게 그리면 그중 하나는 반드시 거짓말이 된다.
          열람 URL 발급·폐기 표시·업로드는 전부 EvidencePanel 안에 있고 여기서 복제하지
          않는다. 캡처 프레임·바운딩박스는 여전히 데이터 경로가 없어 그리지 않는다. */}
      <div className="mx-4 mt-3">
        <EvidencePanel eventKey={event.eventKey} evidence={event.evidence} canUpload={canTriage} />
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
        <Fact label="담당자" value={event.assignee ?? "미배정"} />
        <Fact label="발생 시각" value={<span className="num">{formatDate(event.occurredAt)}</span>} />
        <Fact
          label="확인 경과"
          value={<AckElapsedFact event={event} initialElapsedMs={initialElapsedMs} />}
        />
      </dl>

      <details className="mx-4 mt-3 rounded-lg border border-line px-3 py-2 text-[12px]">
        <summary className="tap-target cursor-pointer font-semibold">전문가 정보</summary>
        <dl className="mt-1 flex flex-col border-t border-line pt-1">
          <Fact label="항목 ID" value={<span className="num break-token">{event.eventKey}</span>} />
          <Fact
            label="비행 임무"
            value={<Link href={`/missions/${encodeURIComponent(event.missionId)}`} className="break-token underline">{missionLabel}</Link>}
          />
          <Fact label="Edge 장치" value={<span className="num break-token">{event.edgeDeviceId}</span>} />
          <Fact label="수신 시각" value={<span className="num">{formatDate(event.receivedAt)}</span>} />
          <Fact label="최근 충돌" value={<span className="num">{formatDate(event.lastConflictAt)}</span>} />
        </dl>
      </details>

      {canTriage && (
        <div className="mx-4 my-3">
          <EventActions
            eventKey={event.eventKey}
            status={event.status}
            triage={event.triage}
            bundleDigest={event.bundleDigest}
          />
        </div>
      )}
    </PanelShell>
  );
}
