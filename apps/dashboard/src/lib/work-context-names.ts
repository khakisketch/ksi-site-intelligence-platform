/**
 * 작업·구역 이름 표시(presentation-only) 헬퍼.
 *
 * Core가 인증 범위로 내려준 `name`을 그대로 옮길 뿐, 이름으로 구역 소속·분석
 * 준비 상태·권한을 추론하지 않는다(INV-053/060/061). 회차는
 * `workOrder.cycleNumber` 원값만 쓰고 이름 접미사(t1/t2 등)에서 유도하지
 * 않는다. 이름이 없으면 ID를 지어내지 않고 "확인 불가"로 정직하게 둔다.
 * 기술 ID는 접을 수 있는 참조(details/summary)로만 노출한다.
 */

import { formatKoreanDateTime } from "@/lib/datetime";
import { formatCountKo } from "@/lib/number-format";

export const SITE_NAME_UNAVAILABLE = "현장 이름 확인 불가";
export const WORK_AREA_NAME_UNAVAILABLE = "구역 이름 확인 불가";

/** 이미 읽어 둔 WorkArea 목록을 id → name 색인으로 접는다. 보관 상태는 제외하지 않는다. */
export function indexWorkAreaNames(
  areas: readonly { workAreaId: string; name: string }[],
): Map<string, string> {
  const byId = new Map<string, string>();
  for (const area of areas) {
    // 빈 이름은 알려진 이름이 아니다 — 그대로 두면 빈 맥락이 된다.
    // 공백이 아닌 이름은 표시용으로 정확히 보존한다(다듬지 않는다).
    if (area.name.trim() === "" || byId.has(area.workAreaId)) continue;
    byId.set(area.workAreaId, area.name);
  }
  return byId;
}

/**
 * 현장별 구역 이름 색인. 작업구역 ID는 현장 안에서만 유일하므로
 * 현장끼리 평평하게 합치지 않는다 — 다른 현장의 같은 ID가 섞이지 않게 한다.
 */
export function indexWorkAreaNamesBySite(
  pages: readonly { siteId: string; workAreas: readonly { workAreaId: string; name: string }[] }[],
): Map<string, Map<string, string>> {
  const bySite = new Map<string, Map<string, string>>();
  for (const page of pages) {
    const scoped = bySite.get(page.siteId) ?? new Map<string, string>();
    for (const [workAreaId, name] of indexWorkAreaNames(page.workAreas)) {
      if (!scoped.has(workAreaId)) scoped.set(workAreaId, name);
    }
    bySite.set(page.siteId, scoped);
  }
  return bySite;
}

export interface WorkAreaDisplayNames {
  known: string[];
  unknownCount: number;
}

/** 작업의 구역 ID들을 알려진 이름과 미확인 건수로 나눈다. 순서는 원장 순서를 따른다. */
export function selectWorkAreaDisplayNames(
  workAreaIds: readonly string[],
  nameById: ReadonlyMap<string, string>,
): WorkAreaDisplayNames {
  const known: string[] = [];
  let unknownCount = 0;
  for (const workAreaId of workAreaIds) {
    const name = nameById.get(workAreaId);
    // 색인에 빈 이름이 들어 있어도 미확인으로 둔다(표시는 정확한 이름만).
    if (name === undefined || name.trim() === "") unknownCount += 1;
    else if (!known.includes(name)) known.push(name);
  }
  return { known, unknownCount };
}

/**
 * 구역 요약 한 줄. 알려진 이름이 앞서고 나머지는 개수만 적는다 —
 * 미확인 ID를 문장 주어로 쓰지 않고 회차를 유도하지도 않는다.
 */
export function formatWorkAreaSummary(
  workAreaIds: readonly string[],
  nameById: ReadonlyMap<string, string>,
  maxShown = 2,
): string {
  if (workAreaIds.length === 0) return "구역 지정 없음";
  const { known } = selectWorkAreaDisplayNames(workAreaIds, nameById);
  const shown = known.slice(0, Math.max(1, maxShown));
  const remaining = workAreaIds.length - shown.length;
  if (shown.length === 0) return `${formatCountKo(workAreaIds.length)}개 구역 (${WORK_AREA_NAME_UNAVAILABLE})`;
  if (remaining === 0) return shown.join(" · ");
  return `${shown.join(" · ")} 외 ${formatCountKo(remaining)}개 구역`;
}

export interface WorkQueueRowContext {
  siteName: string | null;
  workAreaIds: readonly string[];
  nameById: ReadonlyMap<string, string>;
  /** Core 원장의 cycleNumber 원값. 이름에서 유도하지 않는다. */
  cycleNumber: number;
  updatedAt: string;
}

/** 작업 큐 행의 맥락 한 줄: 현장 · 구역 · 정식 회차 · 갱신 시각. */
export function formatWorkQueueRowContext(context: WorkQueueRowContext): string {
  const site = context.siteName ?? SITE_NAME_UNAVAILABLE;
  const areas = formatWorkAreaSummary(context.workAreaIds, context.nameById);
  const updated = formatKoreanDateTime(context.updatedAt, { dateStyle: "medium", timeStyle: "short" });
  return `${site} · ${areas} · ${formatCountKo(context.cycleNumber)}회차 · 갱신 ${updated}`;
}

export interface WorkQueueDisplayGroup<Row> {
  key: string;
  rows: readonly Row[];
}

/**
 * 비어 있지 않은 그룹을 먼저 둔다(안정 정렬). 행 자체는 손대지 않아
 * 요약 건수와 그룹 소속은 그대로 유지된다.
 */
export function orderWorkQueueGroupsForDisplay<Group extends WorkQueueDisplayGroup<unknown>>(
  groups: readonly Group[],
): Group[] {
  return [...groups].sort((left, right) => Number(right.rows.length > 0) - Number(left.rows.length > 0));
}

export interface WorkQueueRowContextNeed {
  name: string;
  siteName: string | null;
  workAreaIds: readonly string[];
  nameById: ReadonlyMap<string, string>;
}

/**
 * 사람이 읽는 맥락이 빠져 있는 행. 이름이 비었거나 현장·구역 이름을
 * 확인하지 못하면 행 기술 참조를 둔다(진단 ID는 상세 화면에 남는다).
 */
export function isWorkQueueContextMissing(row: WorkQueueRowContextNeed): boolean {
  if (row.name.trim() === "") return true;
  if (row.siteName === null) return true;
  return selectWorkAreaDisplayNames(row.workAreaIds, row.nameById).unknownCount > 0;
}

export interface WorkQueueRowDisclosureNeed {
  rowKey: string;
  name: string;
  /** 화면에 그대로 찍히는 맥락 한 줄(현장 · 구역 · 회차 · 갱신). */
  contextLine: string;
  missingContext: boolean;
}

/**
 * 행 기술 참조가 필요한 행 키 집합. 맥락이 빠진 행, 또는 이름+맥락 한 줄이
 * 서로 겹쳐 눈으로 가를 수 없는 행만 펼침 대상으로 둔다. 유일하게 식별되는
 * 행은 compact하게 두고 전체 ID는 작업 상세 화면에서 계속 볼 수 있다.
 */
export function selectWorkQueueRowsNeedingTechnicalRef(
  rows: readonly WorkQueueRowDisclosureNeed[],
): ReadonlySet<string> {
  const needing = new Set<string>();
  const byVisibleIdentity = new Map<string, string[]>();
  for (const row of rows) {
    if (row.missingContext) needing.add(row.rowKey);
    const visibleIdentity = `${row.name}\u0000${row.contextLine}`;
    const bucket = byVisibleIdentity.get(visibleIdentity) ?? [];
    bucket.push(row.rowKey);
    byVisibleIdentity.set(visibleIdentity, bucket);
  }
  for (const bucket of byVisibleIdentity.values()) {
    if (bucket.length > 1) {
      for (const rowKey of bucket) needing.add(rowKey);
    }
  }
  return needing;
}

export interface HomeAnalysisReviewCardContext {
  siteName: string | null;
  workAreaId: string;
  areaName: string | null;
}

/** Home은 해야 할 행동으로 이끌고, 실제 구역 이름은 대상 맥락으로 보존한다. */
export function homeAnalysisReviewCardText(context: HomeAnalysisReviewCardContext): {
  title: string;
  detail: string;
} {
  const site = context.siteName ?? SITE_NAME_UNAVAILABLE;
  if (context.areaName) {
    return {
      title: "분석 결과를 검토하세요.",
      detail: `대상 구역 · ${context.areaName}. 현재 결과의 검토 기록이 없습니다. 결과와 근거를 확인하세요.`,
    };
  }
  return {
    title: "완료된 분석 결과를 검토하세요.",
    detail: `${site} — 완료된 분석 결과에 현재 결과를 대상으로 한 검토 기록이 없습니다. 구역 이름을 확인하지 못했습니다. 결과와 근거를 확인하세요.`,
  };
}

/** 기술 참조용 구역 ID 나열. 같은 이름에 접힌 구역 ID도 여기서 모두 보인다. */
export function formatWorkAreaTechnicalRefs(workAreaIds: readonly string[]): string {
  return workAreaIds.length > 0 ? workAreaIds.join(", ") : "지정 없음";
}

/** 카드에 접어 두는 기술 참조 한 줄(키보드 도달 가능 details의 본문용). */
export function formatHomeReviewTechnicalRef(analysisId: string, workAreaId: string): string {
  return `분석 ${analysisId} · 작업구역 ${workAreaId}`;
}

export interface InboxTargetContext {
  workName: string | null;
  siteName: string | null;
}

export interface SplitInboxItemContext {
  /** 작업 이름 줄. 없으면 null이다. */
  title: string | null;
  /** 현장 줄. 없으면 null이다. */
  siteLine: string | null;
}

/**
 * 받은 업무 항목의 맥락 두 줄. 작업 이름과 현장을 분리해 긴 이름이 현장
 * 식별자를 잘라내지 않게 한다. 확인할 수 있는 이름만 쓰고, 없으면 null을
 * 돌려줘 호출자가 ID를 산문으로 찍지 않게 한다.
 */
export function splitInboxItemContext(
  kind: "WORK_ORDER_ASSIGNED" | "EXTERNAL_REPORT_SHARED",
  context: InboxTargetContext,
): SplitInboxItemContext {
  if (kind === "WORK_ORDER_ASSIGNED") {
    return { title: context.workName, siteLine: context.siteName };
  }
  return { title: null, siteLine: context.siteName ? `${context.siteName}의 공유 결과` : null };
}
