import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import { assignCrsSwatches, normalizeCrs } from "@/lib/crs-match";
import { isAnalysisCrs } from "@/lib/geo/known-crs";
import { koreanCalendarDate } from "@/lib/observation-default-name";
import {
  observationPrecisionOf,
  parseCalendarDate,
  representativeFacts,
  type CapturePrecision,
  type WorkspaceObservationFact,
  type WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";

import { CAPTURE_STRIP_WIDTH, layoutCaptureStrip } from "./areas/area-summary";

/**
 * 비교 모드 "자료 날짜" 시간 띠의 순수 모델 — 렌더링과 Core 호출을 모른다.
 *
 * 여기서 만드는 값은 모두 **화면 표시용 힌트**다. 두 자료를 같은 좌표계로 보아 비교·체적을 열지는
 * Core가 다시 판정한다(INV-020). 시간 순서는 서버의 `chronologyCandidate`를 그대로 따르고, 그 위에
 * 시작·종료가 모두 있는 구간(interval)만 순서 있는 점으로 그린다. 날짜만·미상·같은 구간은 순서를
 * 정할 수 없으므로 점이 아니라 "순서 미정" 목록으로 둔다 — 없는 시각을 만들지 않는다.
 */

export type TimelineStatus = "OK" | "ONLY_ONE" | "NOT_READY" | "CRS_MISMATCH" | "NO_ORDERABLE";

/** 점 라벨에 연도를 붙이는 기준 — 띠에 오른 날짜가 해를 넘거나 이만큼(일) 넘게 벌어진다. */
export const YEAR_LABEL_SPAN_DAYS = 330;

/** 점을 고를 수 없게 흐리는 이유. 선택된 점은 흐리지 않는다. 분석 밖 좌표계는 흐리는 이유가 아니다(칩으로만 알린다). */
export type TimelineDimReason = "no-height" | "not-ready" | "crs-different";

export type TimelineRole = "baseline" | "current";

export type TimelinePair = { baselineAssetRef: string; currentAssetRef: string };

export type TimelinePoint = {
  /** 관측(epoch) 식별자 — 점은 관측마다 하나다. */
  key: string;
  /** 주소에 실을 대표 자료 참조(표시 버전). */
  assetRef: string;
  kind: string;
  /** 한국 달력 날짜(YYYY-MM-DD). 구간의 시작 시각에서 읽는다. */
  date: string;
  startMs: number;
  /** 같은 날짜에 점이 둘 이상일 때만 채우는 시각(HH:mm, 한국 시간). */
  time: string | null;
  /** 정규화한 관측 좌표계. DSM이 아니거나 검사 전이면 null. */
  crs: string | null;
  /** 분석 좌표계만 1~5. 분석 밖·모름은 null(회색). */
  swatch: number | null;
  dimmed: TimelineDimReason | null;
  role: TimelineRole | null;
  /** 이 점을 눌렀을 때 가게 될 이전·이후 쌍. 고를 수 없으면 null. */
  pair: TimelinePair | null;
  /** 이 점을 누르면 이전/이후 중 어느 쪽이 되는지(이름표용). */
  becomes: TimelineRole | null;
};

export type TimelineSlot = {
  date: string;
  /** 띠 안의 가로 위치(0~100%). */
  leftPercent: number;
  points: TimelinePoint[];
};

export type UnorderedReason = "date-only" | "unknown" | "tie";

export type UnorderedItem = {
  key: string;
  assetRef: string;
  kind: string;
  reason: UnorderedReason;
  /** 날짜만 아는 경우·같은 구간의 경우의 날짜. 미상이면 null. */
  date: string | null;
};

export type CompareTimeline = {
  status: TimelineStatus;
  /** 띠에 올린 날짜 칸(오래된 순). 최근 8개까지다. */
  slots: TimelineSlot[];
  /** 순서 있는 점 전체 개수와 띠에 못 올린 수. */
  orderedCount: number;
  hiddenCount: number;
  unordered: UnorderedItem[];
  /** 높이 자료(DSM)이고 표시 준비된 순서 있는 점 수. */
  heightCount: number;
  /** 높이 자료(DSM)인 순서 있는 점 전체 수(표시 준비 여부와 무관). */
  heightTotal: number;
  /** 그중 표시 준비 전인 수. */
  notReadyCount: number;
  /** 띠에 오른 날짜가 해를 넘거나 330일을 넘게 벌어져 점 라벨에 연도를 둔다. */
  yearLabels: boolean;
  /** 분석 좌표계 중 기준으로 삼은 것. 없으면 null. */
  referenceCrs: string | null;
  referenceSwatch: number | null;
  baseline: TimelinePoint | null;
  current: TimelinePoint | null;
  /** 이전·이후 사이 일수(한국 달력). 둘 다 골랐을 때만. */
  days: number | null;
  /** 이전이 이후보다 늦다(주소로 거꾸로 온 경우). */
  reversed: boolean;
  /** 고른 두 점의 좌표계가 둘 다 읽혔고 서로 다르다. */
  selectionCrsMismatch: boolean;
  /** 날짜 낭독에 연도를 붙여야 하는가(점들의 연도가 여러 개). */
  withYear: boolean;
  /** 점을 하나라도 누를 수 있는가(안내 문구용). */
  hasPickable: boolean;
  /** 서버가 해석한 쌍을 요청했는데 띠에서 두 점을 찾지 못했다. */
  selectionMissing: boolean;
};

function startMsOf(fact: WorkspaceObservationFact): number | null {
  const ms = Date.parse(fact.captureStartedAt ?? "");
  return Number.isFinite(ms) ? ms : null;
}

function endMsOf(fact: WorkspaceObservationFact): number | null {
  const ms = Date.parse(fact.captureEndedAt ?? "");
  return Number.isFinite(ms) ? ms : null;
}

function koreanClock(ms: number): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(ms));
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "00";
  return `${pick("hour")}:${pick("minute")}`;
}

function dayNumber(date: string): number {
  return Date.parse(`${date}T00:00:00Z`) / 86_400_000;
}

type Draft = {
  fact: WorkspaceObservationFact;
  startMs: number;
  date: string;
  ready: boolean;
  isHeight: boolean;
  crs: string | null;
};

export function buildCompareTimeline(input: {
  facts: WorkspaceServerFacts;
  workAreaId: string;
  catalogAssets: readonly SpatialAssetCatalogItem[];
  /** 영역 경계의 좌표계 — 기준 좌표계가 같은 건수일 때 한쪽을 고르는 데만 쓴다. */
  areaCrs?: string | null;
  baselineAssetRef?: string | null;
  currentAssetRef?: string | null;
  /** 서버가 "같은 촬영 구간이라 고르지 않았다"고 알린 관측들(entryDefault). */
  tiedEpochIds?: readonly string[];
}): CompareTimeline {
  const { facts, workAreaId, catalogAssets } = input;
  const catalogByRef = new Map(catalogAssets.map((item) => [item.assetRef, item]));
  const reps = representativeFacts(facts, workAreaId);

  // 1) 순서 있는 점 / 순서 미정으로 가른다 — 서버의 chronologyCandidate와 구간 정밀도를 둘 다 만족해야 점이다.
  const drafts: Draft[] = [];
  const unordered: UnorderedItem[] = [];
  const serverTied = new Set(input.tiedEpochIds ?? []);
  for (const fact of reps) {
    const precision: CapturePrecision = observationPrecisionOf(fact);
    const startMs = startMsOf(fact);
    if (!fact.chronologyCandidate || precision !== "interval" || startMs === null) {
      unordered.push({
        key: fact.observationEpochId,
        assetRef: fact.assetRef,
        kind: fact.kind,
        reason: precision === "date-only" ? "date-only" : "unknown",
        date: precision === "date-only" ? parseCalendarDate(fact.captureDate) : null,
      });
      continue;
    }
    const item = catalogByRef.get(fact.assetRef) ?? null;
    const measured = item !== null && item.inspection.outcome === "MEASURED";
    drafts.push({
      fact,
      startMs,
      date: koreanCalendarDate(new Date(startMs)),
      ready: fact.displayReady && fact.viewAvailable,
      isHeight: fact.kind === "dsm",
      crs: fact.kind === "dsm" && measured ? normalizeCrs(item.inspection.raster?.observedCrsIdentifier) : null,
    });
  }

  // 같은 구간(시작·종료가 모두 같음)이거나 서버가 동률이라 알린 관측은 앞뒤를 정할 수 없다.
  const intervalKey = (draft: Draft) => `${draft.startMs}:${endMsOf(draft.fact)}`;
  const intervalCounts = new Map<string, number>();
  for (const draft of drafts) intervalCounts.set(intervalKey(draft), (intervalCounts.get(intervalKey(draft)) ?? 0) + 1);
  const ordered = drafts.filter((draft) => {
    const tied = (intervalCounts.get(intervalKey(draft)) ?? 0) > 1 || serverTied.has(draft.fact.observationEpochId);
    if (tied) {
      unordered.push({
        key: draft.fact.observationEpochId,
        assetRef: draft.fact.assetRef,
        kind: draft.fact.kind,
        reason: "tie",
        date: draft.date,
      });
    }
    return !tied;
  }).sort((a, b) => a.startMs - b.startMs || a.fact.observationEpochId.localeCompare(b.fact.observationEpochId));

  // 2) 기준 좌표계 — 고른 자료의 분석 좌표계가 먼저, 없으면 높이 자료에서 가장 많은 분석 좌표계.
  const epochOfRef = (ref: string | null | undefined): string | null =>
    ref ? (facts.observations.find((item) => item.workAreaId === workAreaId && item.assetRef === ref)?.observationEpochId ?? null) : null;
  const baselineEpoch = epochOfRef(input.baselineAssetRef);
  const currentEpoch = epochOfRef(input.currentAssetRef);
  const baselineDraft = ordered.find((draft) => draft.fact.observationEpochId === baselineEpoch) ?? null;
  const currentDraft = ordered.find((draft) => draft.fact.observationEpochId === currentEpoch) ?? null;
  const selection = baselineDraft !== null && currentDraft !== null && baselineDraft !== currentDraft
    ? { baseline: baselineDraft, current: currentDraft }
    : null;

  // 기준 좌표계 — 높이 DSM을 읽은 좌표계(normalizeCrs)로 묶는다. 짝이 되는 건 같은 좌표계끼리다.
  // 고른 쌍이 있으면 이전 자료의 좌표계, 없으면 짝이 될 수 있는(2건 이상) 그룹 → 분석 좌표계 → 건수 많은 쪽 →
  // 영역 좌표계 → 가장 이른 촬영 순이다. 분석 밖 좌표계도 기준이 될 수 있다 — 분석 가능 여부는 분석 화면이 판단한다.
  const heightDrafts = ordered.filter((draft) => draft.isHeight && draft.ready);
  const areaCrs = normalizeCrs(input.areaCrs);
  const crsGroups = new Map<string, { count: number; firstMs: number }>();
  for (const draft of heightDrafts) {
    if (draft.crs === null) continue;
    const group = crsGroups.get(draft.crs) ?? { count: 0, firstMs: draft.startMs };
    group.count += 1;
    group.firstMs = Math.min(group.firstMs, draft.startMs);
    crsGroups.set(draft.crs, group);
  }
  const dominantCrs = [...crsGroups.entries()].sort(([codeA, a], [codeB, b]) =>
    Number(b.count >= 2) - Number(a.count >= 2)
    || Number(isAnalysisCrs(codeB)) - Number(isAnalysisCrs(codeA))
    || b.count - a.count
    || Number(codeB === areaCrs) - Number(codeA === areaCrs)
    || a.firstMs - b.firstMs
    || codeA.localeCompare(codeB))[0]?.[0] ?? null;
  const selectedCrs = selection ? (selection.baseline.crs ?? selection.current.crs) : null;
  const referenceCrs = selectedCrs ?? dominantCrs;
  const swatches = assignCrsSwatches([
    ...(referenceCrs && isAnalysisCrs(referenceCrs) ? [referenceCrs] : []),
    ...ordered.map((draft) => draft.crs).filter((crs): crs is string => crs !== null && isAnalysisCrs(crs)),
  ]);

  // 3) 점마다 흐림 이유. 순서 → 높이 자료 → 표시 준비 → 좌표계 순으로 가장 먼저 걸리는 하나만 말한다.
  const dimOf = (draft: Draft): TimelineDimReason | null => {
    if (!draft.isHeight) return "no-height";
    if (!draft.ready) return "not-ready";
    if (draft.crs === null) return null; // 좌표계를 아직 읽지 못함 — 단정하지 않고 고를 수 있게 둔다.
    return referenceCrs !== null && draft.crs !== referenceCrs ? "crs-different" : null;
  };

  const years = new Set(ordered.map((draft) => draft.date.slice(0, 4)));
  const sameDateCount = new Map<string, number>();
  for (const draft of ordered) sameDateCount.set(draft.date, (sameDateCount.get(draft.date) ?? 0) + 1);

  // 띠에 올릴 날짜 — 최근 8개. 고른 두 날짜는 오래되어도 반드시 올린다. 짝 후보도 올라온 점으로 한정한다.
  const allDates = [...new Set(ordered.map((draft) => draft.date))].sort();
  const selectedDates = new Set(selection ? [selection.baseline.date, selection.current.date] : []);
  const room = Math.max(0, 8 - selectedDates.size);
  const recent = allDates.filter((date) => !selectedDates.has(date)).slice(-room);
  const shownDates = [...new Set([...selectedDates, ...recent])].sort();
  const shownSet = new Set(shownDates);

  // 4) 눌렀을 때의 쌍. 시간 순서가 뒤집히지 않게 항상 (이전, 이후) 순으로 만든다.
  const pickable = (draft: Draft) => dimOf(draft) === null;
  const baselineSide = selection ? { draft: selection.baseline, ref: input.baselineAssetRef ?? selection.baseline.fact.assetRef } : null;
  const currentSide = selection ? { draft: selection.current, ref: input.currentAssetRef ?? selection.current.fact.assetRef } : null;
  const reversed = Boolean(selection && selection.baseline.startMs > selection.current.startMs);
  const lo = reversed ? currentSide : baselineSide;
  const hi = reversed ? baselineSide : currentSide;

  const pairFor = (draft: Draft): { pair: TimelinePair; becomes: TimelineRole } | null => {
    if (!pickable(draft) && draft !== selection?.baseline && draft !== selection?.current) return null;
    if (lo && hi) {
      if (draft === lo.draft || draft === hi.draft) {
        return { pair: { baselineAssetRef: lo.ref, currentAssetRef: hi.ref }, becomes: draft === lo.draft ? "baseline" : "current" };
      }
      if (draft.startMs < lo.draft.startMs) return { pair: { baselineAssetRef: draft.fact.assetRef, currentAssetRef: hi.ref }, becomes: "baseline" };
      if (draft.startMs > hi.draft.startMs) return { pair: { baselineAssetRef: lo.ref, currentAssetRef: draft.fact.assetRef }, becomes: "current" };
      // 두 점 사이 — 가까운 쪽이 바뀐다(같은 거리면 이후).
      return draft.startMs - lo.draft.startMs < hi.draft.startMs - draft.startMs
        ? { pair: { baselineAssetRef: draft.fact.assetRef, currentAssetRef: hi.ref }, becomes: "baseline" }
        : { pair: { baselineAssetRef: lo.ref, currentAssetRef: draft.fact.assetRef }, becomes: "current" };
    }
    // 쌍이 아직 없다 — 고른 점이 이후, 바로 앞의 누를 수 있는 점이 이전. 앞이 없으면 고른 점이 이전, 바로 뒤가 이후.
    const others = ordered.filter((other) => other !== draft && pickable(other) && shownSet.has(other.date));
    const before = [...others].reverse().find((other) => other.startMs < draft.startMs) ?? null;
    if (before) return { pair: { baselineAssetRef: before.fact.assetRef, currentAssetRef: draft.fact.assetRef }, becomes: "current" };
    const after = others.find((other) => other.startMs > draft.startMs) ?? null;
    if (after) return { pair: { baselineAssetRef: draft.fact.assetRef, currentAssetRef: after.fact.assetRef }, becomes: "baseline" };
    return null;
  };

  const points = new Map<string, TimelinePoint>();
  for (const draft of ordered) {
    const role: TimelineRole | null = draft === selection?.baseline ? "baseline" : draft === selection?.current ? "current" : null;
    const resolved = pairFor(draft);
    points.set(draft.fact.observationEpochId, {
      key: draft.fact.observationEpochId,
      assetRef: draft.fact.assetRef,
      kind: draft.fact.kind,
      date: draft.date,
      startMs: draft.startMs,
      time: (sameDateCount.get(draft.date) ?? 0) > 1 ? koreanClock(draft.startMs) : null,
      crs: draft.crs,
      swatch: draft.crs !== null && isAnalysisCrs(draft.crs) ? (swatches.get(draft.crs) ?? null) : null,
      dimmed: role === null ? dimOf(draft) : null,
      role,
      pair: resolved?.pair ?? null,
      becomes: resolved?.becomes ?? null,
    });
  }

  const strip = layoutCaptureStrip(shownDates);
  const slots: TimelineSlot[] = strip
    ? strip.points.map((point) => ({
      date: point.date,
      leftPercent: Math.round((point.x / CAPTURE_STRIP_WIDTH) * 1000) / 10,
      points: ordered
        .filter((draft) => draft.date === point.date)
        .map((draft) => points.get(draft.fact.observationEpochId)!),
    }))
    : [];
  const shownCount = slots.reduce((sum, slot) => sum + slot.points.length, 0);

  const baseline = selection ? (points.get(selection.baseline.fact.observationEpochId) ?? null) : null;
  const current = selection ? (points.get(selection.current.fact.observationEpochId) ?? null) : null;
  const days = baseline && current ? Math.round(Math.abs(dayNumber(current.date) - dayNumber(baseline.date))) : null;
  const selectionCrsMismatch = Boolean(baseline && current && baseline.crs && current.crs && baseline.crs !== current.crs);

  // 상태는 고른 쌍과 무관하게 정한다 — 같은 좌표계로 묶이는(아직 모르는 것 포함) 높이 자료가 둘 이상인가.
  const notReadyCount = ordered.filter((draft) => draft.isHeight && !draft.ready).length;
  const heightTotal = heightDrafts.length + notReadyCount;
  const spanDays = shownDates.length > 1 ? dayNumber(shownDates[shownDates.length - 1]!) - dayNumber(shownDates[0]!) : 0;
  const yearLabels = new Set(shownDates.map((date) => date.slice(0, 4))).size > 1 || spanDays > YEAR_LABEL_SPAN_DAYS;
  const usable = heightDrafts.filter((draft) => draft.crs === null || draft.crs === dominantCrs);
  const status: TimelineStatus = ordered.length === 0
    ? "NO_ORDERABLE"
    : heightDrafts.length < 2
      ? (heightTotal >= 2 ? "NOT_READY" : "ONLY_ONE")
      : usable.length < 2
        ? "CRS_MISMATCH"
        : "OK";

  return {
    status,
    slots,
    orderedCount: ordered.length,
    hiddenCount: ordered.length - shownCount,
    unordered,
    heightCount: heightDrafts.length,
    heightTotal,
    notReadyCount,
    yearLabels,
    referenceCrs,
    referenceSwatch: referenceCrs ? (swatches.get(referenceCrs) ?? null) : null,
    baseline,
    current,
    days,
    reversed,
    selectionCrsMismatch,
    withYear: years.size > 1,
    selectionMissing: Boolean(input.baselineAssetRef && input.currentAssetRef && !selection),
    hasPickable: [...points.values()].some((point) => point.pair !== null),
  };
}

/** "5186" — `EPSG:` 접두를 뗀 짧은 표기. 접두가 없으면 그대로. */
export function shortCrs(crs: string): string {
  return crs.replace(/^EPSG:/i, "");
}

/** 분석에 쓰는 좌표계 목록 안내(상태 카드용) — `ANALYSIS_CRS`와 같은 집합이다(테스트가 대조한다). */
export const ANALYSIS_CRS_HINT = "5179 · 5185–5188 · UTM 51N · 52N";
