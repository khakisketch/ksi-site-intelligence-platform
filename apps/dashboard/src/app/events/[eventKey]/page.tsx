import Link from "next/link";
import { notFound } from "next/navigation";

import { getEvent } from "@/lib/core-api/events";
import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import {
  EVENT_SEVERITY_LABEL,
  EVENT_STATUS_LABEL,
  TRIAGE_STATUS_LABEL,
  humanizeApiError,
} from "@/lib/core-api/labels";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ErrorState } from "@/components/ui/ErrorState";
import { EventActions } from "./EventActions";

const dateFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateFormatter.format(date);
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

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-foreground/60 text-xs break-keep">{label}</dt>
      <dd className="break-keep">{value}</dd>
    </div>
  );
}

function TransitionItem({ transition }: { transition: Record<string, unknown> }) {
  const actor = fieldString(transition, "actor");
  const ts = fieldString(transition, "ts");
  const reason = fieldString(transition, "reason");
  const before = fieldRecord(transition, "before");
  const after = fieldRecord(transition, "after");
  const beforeStatus = fieldString(before, "status");
  const afterStatus = fieldString(after, "status");
  const beforeTriage = fieldString(before, "triage");
  const afterTriage = fieldString(after, "triage");

  return (
    <li className="rounded-lg border border-black/10 p-3 text-sm dark:border-white/10">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium break-keep">{actor ?? "알 수 없음"}</span>
        <span className="text-foreground/60 text-xs">{formatDate(ts)}</span>
      </div>
      {(beforeStatus || afterStatus) && (
        <p className="text-foreground/70 mt-1 break-keep">
          상태: {labelOrRaw(beforeStatus, EVENT_STATUS_LABEL) ?? "—"} →{" "}
          {labelOrRaw(afterStatus, EVENT_STATUS_LABEL) ?? "—"}
        </p>
      )}
      {(beforeTriage || afterTriage) && (
        <p className="text-foreground/70 mt-1 break-keep">
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
      <div className="flex flex-col gap-4 p-4 sm:p-6">
        <Link href="/events" className="text-sm underline break-keep">
          ← 목록으로
        </Link>
        <ErrorState message={message} />
      </div>
    );
  }

  let canTriage = false;
  try {
    const who = await whoAmI();
    canTriage = who.permissions.includes("EVENTS_TRIAGE");
  } catch {
    canTriage = false;
  }

  const confirmation = findConfirmation(event.transitions);

  return (
    <div className="flex flex-col gap-6 p-4 sm:p-6">
      <div>
        <Link href="/events" className="text-sm underline break-keep">
          ← 목록으로
        </Link>
        <h1 className="mt-2 text-lg font-medium break-keep">{event.eventKey}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge
            label={EVENT_STATUS_LABEL[event.status].label}
            tone={EVENT_STATUS_LABEL[event.status].tone}
          />
          {event.severity && (
            <StatusBadge
              label={EVENT_SEVERITY_LABEL[event.severity].label}
              tone={EVENT_SEVERITY_LABEL[event.severity].tone}
            />
          )}
          <StatusBadge
            label={TRIAGE_STATUS_LABEL[event.triage].label}
            tone={TRIAGE_STATUS_LABEL[event.triage].tone}
          />
        </div>
        {confirmation && (
          <p className="text-foreground/70 mt-2 text-sm break-keep">
            확정: {confirmation.actor}, {formatDate(confirmation.ts)}
          </p>
        )}
      </div>

      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
        <Field label="이벤트 키" value={event.eventKey} />
        <Field label="이벤트 ID" value={event.eventId} />
        <Field label="현장" value={event.siteId} />
        <Field label="임무" value={event.missionId} />
        <Field label="엣지 장치" value={event.edgeDeviceId} />
        <Field label="담당자" value={event.assignee ?? "미배정"} />
        <Field label="발생 시각" value={formatDate(event.occurredAt)} />
        <Field label="수신 시각" value={formatDate(event.receivedAt)} />
        <Field label="최근 충돌 시각" value={formatDate(event.lastConflictAt)} />
      </dl>

      {canTriage && (
        <EventActions eventKey={event.eventKey} status={event.status} triage={event.triage} />
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium break-keep">전이 이력</h2>
        {event.transitions.length === 0 ? (
          <p className="text-foreground/60 text-sm break-keep">이력이 없습니다.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {event.transitions.map((t, i) => (
              <TransitionItem key={i} transition={t} />
            ))}
          </ul>
        )}
      </section>

      <details className="rounded-lg border border-black/10 p-3 dark:border-white/10">
        <summary className="cursor-pointer text-sm font-medium break-keep">원본 데이터</summary>
        <pre className="mt-2 max-w-full overflow-x-auto text-xs">
          {JSON.stringify(event.bundle, null, 2)}
        </pre>
      </details>
    </div>
  );
}
