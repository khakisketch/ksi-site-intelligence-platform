// 트리아지 대기열의 순서와 '방치' 판정 — 목록 화면의 도메인 규칙 SSOT.
//
// 화면 컴포넌트가 정렬 비교 함수를 직접 들고 있으면 목록·홈·현장 상세가 서로 다른
// 순서를 보여주게 된다. 규칙은 여기 한 곳에 둔다.

import type { EventSeverity, EventSummaryResponse } from "./types";

// 아직 사람이 손대지 않은 상태. 이 둘의 조합이 '방치'의 정의다 —
// triage 가 NONE 이고(아무도 배정받지 않았고) 종단에 이르지 않은(아직 살아있는) 사건.
const OPEN_TRIAGE = "NONE";
const TERMINAL_STATUSES = new Set(["CONFIRMED_EVENT", "DISMISSED"]);

/** 위험할수록 큰 값. null(미판정)은 판정된 어떤 등급보다도 아래로 둔다. */
const SEVERITY_RANK: Record<EventSeverity, number> = {
  CRITICAL: 4,
  HIGH: 3,
  MEDIUM: 2,
  CANDIDATE: 1,
};

function severityRank(severity: EventSeverity | null): number {
  return severity ? SEVERITY_RANK[severity] : 0;
}

/** 아직 아무도 보지 않은 사건인가. */
export function isUnattended(event: EventSummaryResponse): boolean {
  return event.triage === OPEN_TRIAGE && !TERMINAL_STATUSES.has(event.status);
}

/** 종결된 사건인가 — 대기열에서 항상 맨 아래로 내린다. */
export function isSettled(event: EventSummaryResponse): boolean {
  return TERMINAL_STATUSES.has(event.status);
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// ── 확인(Acknowledge) SLA ────────────────────────────────────────────────
//
// **정본은 `docs/architecture/03_DASHBOARD_UX_GOALS.md` §4.6 이다 (2026-08-04 대표자 확정).**
// 이 값은 화면에 "목표 15분 안에"로 노출되므로 제품 약속이다 — 여기서 바꾸지 말고 문서를 먼저 고친다.
// 인시던트 관리가 MTTA(확인)와 MTTR(해결)을 나누듯 이 제품도 시계가 둘이다:
//   확인 = 사람이 이 감지가 진짜인지 판단하기까지 (status: 관측→확정/오탐)
//   조치 = 확정된 위험을 실제로 제거하기까지   (triage: 배정→해결)
// 여기서는 **확인 시계만** 다룬다. 조치 SLA 는 확정 건이 아직 없어 측정할 대상이 없다.
//
// 값의 근거는 위험성평가 4등급(즉시 작업중지 / 즉시·단기 개선 / 계획적 개선 / 자율)과
// 건설 안전 SaaS 의 통상 기본값이다.
const ACK_SLA_MS: Record<EventSeverity, number> = {
  CRITICAL: 15 * MINUTE,
  HIGH: 1 * HOUR,
  MEDIUM: 4 * HOUR,
  CANDIDATE: 1 * DAY,
};

// 심각도가 아직 안 매겨진 이벤트의 확인 목표.
//
// 이 값이 이 표에서 가장 중요하다. 등급별 SLA 만 두면 미판정 건에는 **어떤 목표도
// 걸리지 않아** 영원히 방치돼도 아무 신호가 없다 — 그런데 판정 전에는 그게 CRITICAL
// 인지 오탐인지 알 수 없으므로, 모르는 것을 오래 두는 것이야말로 가장 위험하다.
// 그래서 등급과 무관하게 일괄로 건다.
export const UNCLASSIFIED_ACK_SLA_MS = 4 * HOUR;

export function ackSlaMs(severity: EventSeverity | null): number {
  return severity ? ACK_SLA_MS[severity] : UNCLASSIFIED_ACK_SLA_MS;
}

export type SlaState = "ok" | "due-soon" | "breached";

/**
 * 확인 SLA 대비 현재 상태. 이미 사람이 붙은 건(=확인된 건)은 판정하지 않는다.
 *
 * `due-soon` 은 목표의 80% 를 넘긴 구간이다 — 초과하고 나서야 빨개지면 예방이 아니라
 * 사후 통보가 된다.
 */
export function ackSlaState(
  event: EventSummaryResponse,
  elapsed: number,
): SlaState | null {
  if (!isUnattended(event)) return null;
  const target = ackSlaMs(event.severity);
  if (elapsed >= target) return "breached";
  if (elapsed >= target * 0.8) return "due-soon";
  return "ok";
}

/**
 * 경과 시간을 사람 말로. 방치된 사건은 '~째'로 진행 중임을 드러낸다.
 *
 * "3시간 전"과 "3시간째 미조치"는 같은 숫자지만 다른 뜻이다 — 전자는 사실,
 * 후자는 아직 끝나지 않았다는 경고다. 안전 대기열에서는 후자가 필요하다.
 */
export function formatElapsed(ms: number, { unattended }: { unattended: boolean }): string {
  const suffix = unattended ? "째 미조치" : " 전";
  if (ms >= DAY) {
    const days = Math.floor(ms / DAY);
    return unattended ? `${days}일${suffix}` : `${days}일${suffix}`;
  }
  if (ms >= HOUR) {
    const hours = Math.floor(ms / HOUR);
    const mins = Math.floor((ms % HOUR) / MINUTE);
    const head = mins > 0 ? `${hours}시간 ${mins}분` : `${hours}시간`;
    return `${head}${suffix}`;
  }
  const mins = Math.floor(ms / MINUTE);
  if (mins < 1) return unattended ? "방금 들어옴" : "방금";
  return `${mins}분${suffix}`;
}

/**
 * 대기열 정렬 — **위험 등급 고정 + 그 아래 방치 시간 순** (2026-08-04 확정).
 *
 * 인시던트 관리(PagerDuty·Opsgenie)와 SIEM 은 심각도 우선 정렬을 쓰고, 방치는 목록
 * 순서가 아니라 에스컬레이션으로 처리한다. 한편 Jira Service Management 계열은
 * SLA 초과분을 상단으로 끌어올린다. 두 관례를 합치면 "위험은 항상 위, 그 아래는
 * 방치 시간 순"이 되고, 안전 크리티컬 화면에서 위험 건이 아래로 밀리는 사고를 막는다.
 *
 * 정본은 `design/ksi-site-intelligence/studies/sort-hybrid.html` 이다 — 고정 그룹에 들어가는
 * 것은 **위험(CRITICAL)뿐**이고 높음(HIGH)은 아래 방치 시간 순 그룹에 놓인다.
 *
 * 지금은 severity 가 전부 null 이라 위험 그룹이 비어 결과적으로 방치 순과 같아진다 —
 * 인지 파이프라인이 등급을 채우기 시작하면 규칙이 자연히 작동한다.
 */
export function sortForTriage<T extends EventSummaryResponse>(events: readonly T[]): T[] {
  return [...events].sort((a, b) => {
    // 1) 종결된 건은 언제나 맨 아래 — 대기열은 '할 일'이지 '기록'이 아니다.
    const settled = Number(isSettled(a)) - Number(isSettled(b));
    if (settled !== 0) return settled;

    // 2) 위험(CRITICAL)만 상단 고정.
    //
    // 임계값이 HIGH 였는데 정본과 어긋나 있었다(2026-08-04 수정). 정본인 정렬 연구
    // `design/ksi-site-intelligence/studies/sort-hybrid.html` 은 "위험 등급 · 항상 최상단"
    // 그룹에 sev-crit 만 넣고 sev-high 는 아래 "그 외 · 방치 시간 순" 그룹에 둔다
    // (연구 본문: "위험 2건을 위로 고정하고 그 아래를 방치 시간 순으로").
    //
    // 이 구분이 중요한 이유: 고정 그룹이 넓어질수록 그 안에서는 방치 시간이 무시된다.
    // HIGH 까지 올리면 "3일 방치된 HIGH"와 "방금 들어온 HIGH"가 같은 층에 놓여, 정작
    // 이 화면이 막으려던 실패(감지했는데 아무도 안 봄)를 다시 만든다. 고정은 좁을수록 좋다.
    //
    // 현재 severity 는 전량 null 이라 이 변경의 런타임 효과는 0이다 — 인지 파이프라인이
    // 등급을 채우기 시작할 때 올바른 규칙이 이미 들어가 있게 지금 맞춰 둔다.
    const aTop = severityRank(a.severity) >= SEVERITY_RANK.CRITICAL;
    const bTop = severityRank(b.severity) >= SEVERITY_RANK.CRITICAL;
    if (aTop !== bTop) return aTop ? -1 : 1;
    if (aTop && bTop) {
      const bySeverity = severityRank(b.severity) - severityRank(a.severity);
      if (bySeverity !== 0) return bySeverity;
    }

    // 3) 같은 층 안에서는 오래된 것이 위로.
    return new Date(a.occurredAt).getTime() - new Date(b.occurredAt).getTime();
  });
}

/** 정렬 결과를 화면에 보이는 그룹으로 쪼갠다 — 규칙이 안 보이면 순서를 믿을 수 없다. */
export interface TriageGroup<T> {
  key: "priority" | "queue" | "settled";
  heading: string | null;
  events: T[];
}

export function groupForTriage<T extends EventSummaryResponse>(
  events: readonly T[],
): TriageGroup<T>[] {
  const sorted = sortForTriage(events);
  // 임계값은 sortForTriage 와 반드시 같아야 한다 — 정렬과 그룹 경계가 어긋나면
  // 그룹 안에서 순서가 뒤집힌 것처럼 보인다. 정본은 sort-hybrid 연구(위험만 고정).
  const priority = sorted.filter(
    (e) => !isSettled(e) && severityRank(e.severity) >= SEVERITY_RANK.CRITICAL,
  );
  const queue = sorted.filter(
    (e) => !isSettled(e) && severityRank(e.severity) < SEVERITY_RANK.CRITICAL,
  );
  const settled = sorted.filter(isSettled);

  const groups: TriageGroup<T>[] = [];
  // 위험 그룹이 비면 머리글도 내보내지 않는다 — 빈 제목은 '위험이 숨겨졌나'로 읽힌다.
  if (priority.length > 0) {
    groups.push({ key: "priority", heading: "위험 등급 · 항상 최상단", events: priority });
  }
  if (queue.length > 0) {
    groups.push({
      key: "queue",
      // 위험 그룹이 있을 때만 대비 제목을 붙인다. 혼자면 제목 없이 목록만 보인다.
      heading: priority.length > 0 ? "그 외 · 방치 시간 순" : null,
      events: queue,
    });
  }
  if (settled.length > 0) {
    groups.push({ key: "settled", heading: "처리 완료", events: settled });
  }
  return groups;
}
