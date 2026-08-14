import Link from "next/link";
import { notFound } from "next/navigation";

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
import { formatKoreanDateTime } from "@/lib/datetime";
import { EventActions } from "./EventActions";
import { EvidencePanel } from "./EvidencePanel";

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return formatKoreanDateTime(value, { dateStyle: "medium", timeStyle: "short" });
}

function fieldString(record: Record<string, unknown> | undefined, key: string): string | undefined {
  const value = record?.[key];
  return typeof value === "string" ? value : undefined;
}

function fieldRecord(
  record: Record<string, unknown> | undefined,
  key: string,
): Record<string, unknown> | undefined {
  const value = record?.[key];
  return value && typeof value === "object" ? (value as Record<string, unknown>) : undefined;
}

function findConfirmation(
  transitions: Array<Record<string, unknown>>,
): { actor: string; ts: string } | null {
  for (let i = transitions.length - 1; i >= 0; i -= 1) {
    const t = transitions[i];
    const after = fieldRecord(t, "after");
    if (after && fieldString(after, "status") === "CONFIRMED_EVENT") {
      const actor = fieldString(t, "actor");
      const ts = fieldString(t, "ts");
      if (actor && ts) return { actor, ts };
    }
  }
  return null;
}

// transitions 는 서버 저장소의 raw dict 를 그대로 통과시킨 것이라 타입이 느슨하다
// (EventDetailResponse.transitions: Record<string, unknown>[]) — 알려진 상태/트리아지
// 값이면 라벨 SSOT로 번역하고, 모르는 값이면 원문을 그대로 보여준다(§4 위반 없이 방어적으로).
function labelOrRaw<T extends string>(
  value: string | undefined,
  table: Record<T, { label: string }>,
): string | undefined {
  if (!value) return value;
  return (table as Record<string, { label: string } | undefined>)[value]?.label ?? value;
}

// 시안 .fact — 92px 고정 라벨열 + 하단 구분선. label 만 텍스트고 value 는 링크를
// 담을 수 있어야 해서(현장·임무) React.ReactNode 를 받는다.
function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[92px_1fr] items-baseline gap-2.5 border-b border-line py-2 last:border-b-0">
      <dt className="text-ink-muted text-xs break-keep">{label}</dt>
      <dd className="text-ink-1 min-w-0 text-[13px] break-token">{value}</dd>
    </div>
  );
}

// journal 레코드의 kind → 사람이 읽을 행위 이름.
//
// 이 이력은 **전이만 담지 않는다** — 증거 등록·폐기도 같은 원장에 append 되기
// 때문이다(ADR-KSI-010 §1). 그걸 모르는 채 actor 만 읽으면 증거 등록이 행위자
// "알 수 없음"으로 표시된다(2026-08-04 렌더 확인에서 실제로 그렇게 보였다).
const JOURNAL_KIND_LABEL: Record<string, string> = {
  "event-projected": "엣지 수신",
  "event-updated": "엣지 갱신",
  "event-diverged": "엣지 갱신 격리",
  "event-transitioned": "트리아지 전이",
  "evidence-registered": "증거 등록",
  "evidence-tombstoned": "증거 폐기",
};

function TransitionItem({ transition }: { transition: Record<string, unknown> }) {
  const kind = fieldString(transition, "kind");
  const kindLabel = kind ? (JOURNAL_KIND_LABEL[kind] ?? kind) : null;
  const artifactId = fieldString(transition, "artifactId");
  // 증거 레코드는 actor 필드가 없다 — 등록자는 registeredBy 에 있다.
  const actor =
    fieldString(transition, "actor") ??
    fieldString(transition, "registeredBy") ??
    fieldString(transition, "edgeDeviceId");
  const ts = fieldString(transition, "ts");
  const reason = fieldString(transition, "reason");
  const before = fieldRecord(transition, "before");
  const after = fieldRecord(transition, "after");
  const beforeStatus = fieldString(before, "status");
  const afterStatus = fieldString(after, "status");
  const beforeTriage = fieldString(before, "triage");
  const afterTriage = fieldString(after, "triage");

  return (
    <li className="rounded-lg border border-line bg-surface p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium break-keep">
          {kindLabel ? `${kindLabel} · ` : ""}
          {actor ?? "행위자 미기록"}
        </span>
        <span className="text-ink-muted text-xs">{formatDate(ts)}</span>
      </div>
      {artifactId && (
        <p className="num break-token text-ink-2 mt-1 text-[12.5px]">{artifactId}</p>
      )}
      {(beforeStatus || afterStatus) && (
        <p className="text-ink-2 mt-1 break-keep">
          상태: {labelOrRaw(beforeStatus, EVENT_STATUS_LABEL) ?? "—"} →{" "}
          {labelOrRaw(afterStatus, EVENT_STATUS_LABEL) ?? "—"}
        </p>
      )}
      {(beforeTriage || afterTriage) && (
        <p className="text-ink-2 mt-1 break-keep">
          트리아지: {labelOrRaw(beforeTriage, TRIAGE_STATUS_LABEL) ?? "—"} →{" "}
          {labelOrRaw(afterTriage, TRIAGE_STATUS_LABEL) ?? "—"}
        </p>
      )}
      {reason && <p className="mt-1 break-keep">사유: {reason}</p>}
    </li>
  );
}

export default async function EventDetailPage({
  params,
}: {
  params: Promise<{ eventKey: string }>;
}) {
  const { eventKey: rawEventKey } = await params;
  const eventKey = decodeURIComponent(rawEventKey);

  let event;
  try {
    event = await getEvent(eventKey);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      notFound();
    }
    const message =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <Link href="/events" className="text-sm underline break-keep">
          ← 목록으로
        </Link>
        <ErrorState message={message} />
      </div>
    );
  }

  // 현장·임무 이름, 트리아지 권한은 이벤트 조회와 독립 — 하나가 실패해도 나머지는 보여준다.
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

  const confirmation = findConfirmation(event.transitions);
  const severity = event.severity ? EVENT_SEVERITY_LABEL[event.severity] : SEVERITY_UNSET_LABEL;
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <Link href="/events" className="tap-target inline-flex w-fit items-center text-sm underline break-keep">
        ← 목록으로
      </Link>

      <div className="flex flex-col gap-2">
        {/* 시안 .eyebrow — eventKey 는 사람이 읽을 이름이 아니라 식별자다.
            h1 은 humanizeEventType 으로, eventKey 는 작은 눈썹글자로 내린다. */}
        <p className="num text-ink-muted text-[10.5px] font-bold tracking-wide break-token uppercase">
          {event.eventKey}
        </p>
        <h2 className="text-lg font-bold break-keep">{humanizeEventType(event.eventType)}</h2>
        <div className="flex flex-wrap items-center gap-2">
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
        {confirmation && (
          <p className="text-ink-2 text-sm break-keep">
            확정: {confirmation.actor}, {formatDate(confirmation.ts)}
          </p>
        )}
      </div>

      {canTriage && (
        <p className="rounded-lg border border-line bg-sunk px-3 py-2.5 text-[12.5px] break-keep text-ink-2">
          먼저 아래 증거와 전이 이력을 확인한 뒤, 현재 사실에 맞게 트리아지 상태를 변경하세요.
        </p>
      )}

      {/* 확정의 근거가 되는 증거를 전이 이력과 제어보다 먼저 둔다. */}
      <EvidencePanel
        eventKey={event.eventKey}
        evidence={event.evidence}
        canUpload={canTriage}
      />

      {/* 1024+ 2열: 좌 전이 이력 / 우 사실 패널 + 액션(시안 .work 396px 상세 폭에 맞춤). */}
      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-5 xl:grid-cols-[minmax(0,1fr)_396px]">
        <div className="flex flex-col gap-4 lg:col-start-2 lg:sticky lg:top-4">
          <dl className="flex flex-col rounded-lg border border-line bg-surface px-4">
            <Field
              label="현장"
              value={
                <Link
                  href={`/sites/${encodeURIComponent(event.siteId)}`}
                  className="break-token underline"
                >
                  {siteName}
                </Link>
              }
            />
            <Field
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
            <Field label="엣지 장치" value={<span className="num break-token">{event.edgeDeviceId}</span>} />
            <Field label="담당자" value={event.assignee ?? "미배정"} />
            <Field label="발생 시각" value={<span className="num">{formatDate(event.occurredAt)}</span>} />
            <Field label="수신 시각" value={<span className="num">{formatDate(event.receivedAt)}</span>} />
            <Field
              label="최근 충돌 시각"
              value={<span className="num">{formatDate(event.lastConflictAt)}</span>}
            />
          </dl>

          {canTriage && (
            <EventActions
              eventKey={event.eventKey}
              status={event.status}
              triage={event.triage}
              bundleDigest={event.bundleDigest}
            />
          )}
        </div>

        <div className="flex flex-col gap-4 lg:col-start-1 lg:row-start-1">
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium break-keep">전이 이력</h2>
          {event.transitions.length === 0 ? (
            <p className="text-ink-2 text-sm break-keep">이력이 없습니다.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {event.transitions.map((t, i) => (
                <TransitionItem key={i} transition={t} />
              ))}
            </ul>
          )}
        </section>
        </div>
      </div>

      {process.env.NODE_ENV !== "production" && (
        <details className="rounded-lg border border-line bg-surface p-3">
          <summary className="cursor-pointer text-sm font-medium break-keep">
            원본 데이터(개발 전용)
          </summary>
          <pre className="mt-2 max-w-full overflow-x-auto text-xs">
            {JSON.stringify(event.bundle, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
