/**
 * 현장 운영 동선(자료 등록 → 촬영 시점 선택 → 두 시점 비교 → 결과 확인/검토)의
 * 순수 범위 해석 규칙. 표현만 담당한다.
 *
 * - Core 클라이언트·fetch를 import하지 않는다.
 * - 판정·재계산은 하지 않는다 — Core가 준 목록에서 "무엇을 미리 고를지"만 고른다.
 * - 원문 id를 화면에 그대로 두지 않는다(범위 밖 값 공지만 둔다).
 * - INV-020/024/051/053/060/061 불변: 면적·원본·API/RBAC/동결 시도·시간 순서·
 *   네이티브 격자·이그레스 권한·사람 검토 의미를 바꾸지 않는다.
 * - 등록≠검사≠입고, 검사≠승인≠정확도, 사람 확인≠승인을 문구에 남긴다.
 */

export const MAX_JOURNEY_SCOPE_ID_LENGTH = 200;

export type JourneyAreaOption = {
  workAreaId: string;
  name: string;
  status: string;
};

function trimmedSingleId(
  raw: unknown,
  known?: ReadonlySet<string>,
): { kind: "absent" | "single" | "invalid"; value: string | null } {
  if (raw === undefined) return { kind: "absent", value: null };
  if (typeof raw !== "string") return { kind: "invalid", value: null };
  // 계약에 workAreaId 최대 길이는 없다(200은 이름에만 있다). 이미 승인된 Core 목록과
  // 정확히 같은 값이면 길이 상한을 적용하지 않고 그대로 받는다. 모르는 값은 아래
  // 상한·공백 판정을 그대로 거쳐 일반 공지만 둔다(원문 노출 없음).
  if (known?.has(raw)) return { kind: "single", value: raw };
  const trimmed = raw.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_JOURNEY_SCOPE_ID_LENGTH) {
    return { kind: "invalid", value: null };
  }
  return { kind: "single", value: trimmed };
}

function activeAreasOf(areas: readonly JourneyAreaOption[]): JourneyAreaOption[] {
  return areas.filter((area) => area.status === "ACTIVE");
}

/**
 * 관측 자료 등록 진입 범위 해석.
 *
 * 우선순위: 반복 템플릿(이전 비교/작업에서 온 실제 선택) > 명시 workAreaId
 * 표시 의도 > 단일 활성 구역 자동 선택 > 수동 선택.
 * 명시 값이 무효(배열·빈값·보관/타구역·미포함·모르는 긴 값)면 조용히 다른 구역을
 * 고르지 않고 빈 선택 + 일반 공지만 둔다. 원문 값은 돌려주지 않는다. 이미 승인된
 * 목록과 정확히 같은 긴 식별자는 길이 상한 없이 받는다.
 */
export function resolveRegistrationScope(input: {
  areas: readonly JourneyAreaOption[];
  rawWorkAreaId: unknown;
  repeatWorkAreaIds: readonly string[];
}): {
  initialWorkAreaIds: string[];
  scopeNotice: string | null;
  invalidRequested: boolean;
} {
  const active = activeAreasOf(input.areas);
  const activeIds = new Set(active.map((area) => area.workAreaId));
  const repeatValid = input.repeatWorkAreaIds.filter((id) => activeIds.has(id));
  if (repeatValid.length > 0) {
    return { initialWorkAreaIds: repeatValid, scopeNotice: null, invalidRequested: false };
  }
  const parsed = trimmedSingleId(input.rawWorkAreaId, activeIds);
  if (parsed.kind === "absent") {
    if (active.length === 1 && active[0]) {
      return {
        initialWorkAreaIds: [active[0].workAreaId],
        scopeNotice:
          "선택한 구역에서 시작합니다. 범위가 맞는지 확인하고 필요하면 바꾸세요.",
        invalidRequested: false,
      };
    }
    return { initialWorkAreaIds: [], scopeNotice: null, invalidRequested: false };
  }
  if (parsed.kind === "invalid" || !parsed.value || !activeIds.has(parsed.value)) {
    return {
      initialWorkAreaIds: [],
      scopeNotice:
        "요청한 작업구역을 확인하지 못했습니다. 비교할 작업구역을 직접 선택하세요.",
      invalidRequested: true,
    };
  }
  return {
    initialWorkAreaIds: [parsed.value],
    scopeNotice: "선택한 구역에서 시작합니다. 범위가 맞는지 확인하고 필요하면 바꾸세요.",
    invalidRequested: false,
  };
}

/**
 * 변화 분석 진입 범위 해석. 보류 중인 동결 시도·명시 분석 딥링크가 있으면
 * URL 힌트를 쓰지 않는다(호출자가 먼저 가른다).
 */
export function resolveAnalysisScope(input: {
  areas: readonly JourneyAreaOption[];
  rawWorkAreaId: unknown;
  hasPendingAttempt: boolean;
  hasAnalysisDeepLink: boolean;
}): {
  initialWorkAreaId: string;
  scopeNotice: string | null;
  invalidRequested: boolean;
} {
  if (input.hasPendingAttempt || input.hasAnalysisDeepLink) {
    return { initialWorkAreaId: "", scopeNotice: null, invalidRequested: false };
  }
  const active = activeAreasOf(input.areas);
  const activeIds = new Set(active.map((area) => area.workAreaId));
  const parsed = trimmedSingleId(input.rawWorkAreaId, activeIds);
  if (parsed.kind === "absent") {
    if (active.length === 1 && active[0]) {
      return {
        initialWorkAreaId: active[0].workAreaId,
        scopeNotice:
          "선택한 구역에서 시작합니다. 범위가 맞는지 확인하고 필요하면 바꾸세요.",
        invalidRequested: false,
      };
    }
    return { initialWorkAreaId: "", scopeNotice: null, invalidRequested: false };
  }
  if (parsed.kind === "invalid" || !parsed.value || !activeIds.has(parsed.value)) {
    return {
      initialWorkAreaId: "",
      scopeNotice: "요청한 작업구역을 확인하지 못했습니다. 작업구역을 직접 선택하세요.",
      invalidRequested: true,
    };
  }
  return { initialWorkAreaId: parsed.value, scopeNotice: null, invalidRequested: false };
}

export type AnalysisCandidateOption = {
  selector: { workOrderId: string };
  workAreaIds: readonly string[];
};

/**
 * 변화 분석 현재 관측 힌트 해석. 실제 허용 분석 후보 목록 안에 있고 선택
 * 구역과 정확히 묶인 경우에만 쓴다. 후보가 여러 개면 버전을 지어내지 않고
 * 고르지 않는다. 부적격·없음이면 빈 값 + 있는 그대로의 공지만 둔다.
 */
export function resolveAnalysisCurrentHint(input: {
  candidates: readonly AnalysisCandidateOption[];
  workAreaId: string;
  rawCurrentWorkOrderId: unknown;
  hasPendingAttempt: boolean;
  hasAnalysisDeepLink: boolean;
}): { currentWorkOrderId: string | null; notice: string | null } {
  if (input.hasPendingAttempt || input.hasAnalysisDeepLink) return { currentWorkOrderId: null, notice: null };
  // 후보 목록과 정확히 같은 긴 작업 식별자도 길이 상한 없이 받는다. 모호성
  // 검사는 그대로 둔다 — 여러 후보면 고르지 않는다.
  const knownWorkOrderIds = new Set(
    input.candidates
      .filter((candidate) => candidate.workAreaIds.includes(input.workAreaId))
      .map((candidate) => candidate.selector.workOrderId),
  );
  const parsed = trimmedSingleId(input.rawCurrentWorkOrderId, knownWorkOrderIds);
  if (parsed.kind === "absent" || !input.workAreaId) return { currentWorkOrderId: null, notice: null };
  if (parsed.kind === "invalid" || !parsed.value) {
    return {
      currentWorkOrderId: null,
      notice: "요청한 관측을 분석 후보에서 확인하지 못했습니다. 현재 관측을 직접 선택하세요.",
    };
  }
  const matches = input.candidates.filter(
    (candidate) =>
      candidate.selector.workOrderId === parsed.value && candidate.workAreaIds.includes(input.workAreaId),
  );
  if (matches.length === 0) {
    return {
      currentWorkOrderId: null,
      notice: "요청한 관측은 이 구역의 분석 후보에 없습니다. 현재 관측을 직접 선택하세요.",
    };
  }
  if (matches.length > 1) {
    return {
      currentWorkOrderId: null,
      notice: "요청한 관측에 후보가 여러 개 있어 자동으로 고르지 않았습니다. 현재 관측을 직접 선택하세요.",
    };
  }
  return { currentWorkOrderId: parsed.value, notice: null };
}

/**
 * 작업 상세에서 이어지는 범위 확인. 원래 연결이 정확히 하나의 구역이고 그
 * 구역이 현행 활성 승인 범위일 때만 미리 고른다. 비활성·모르는 연결을 먼저
 * 걸러내고 하나로 만들지 않는다 — 다구역 작업은 목록에서 직접 고르게 둔다.
 */
export function resolveWorkOrderContinuation(input: {
  areas: readonly JourneyAreaOption[];
  workAreaIds: readonly string[];
}): { workAreaId: string | null } {
  const unique = [...new Set(input.workAreaIds)];
  if (unique.length !== 1 || !unique[0]) return { workAreaId: null };
  const activeIds = new Set(activeAreasOf(input.areas).map((area) => area.workAreaId));
  return activeIds.has(unique[0]) ? { workAreaId: unique[0] } : { workAreaId: null };
}

export type SiteHeaderScope = {
  workAreaId: string | null;
  assetRef: string | null;
};

/**
 * 현장 헤더 메뉴의 목적지. 판정은 하지 않고 이미 검증된 범위만 그대로 싣는다.
 *
 * - 분석·검토와 등록 자료는 실제 라우트로 바로 간다. 루트 `?section=` 경유와 두 번째
 *   클릭을 두지 않는다. 작업구역이 있으면 함께 싣고, 등록 자료에는 같은 목록에서
 *   확인한 자산 참조까지 싣는다(원문 쿼리를 그대로 믿지 않는다 — 호출자가 검증된
 *   값만 넘긴다).
 * - 현황·작업·관리는 기존 루트 섹션을 쓴다(옛 깊은 URL도 같은 화면으로 해석된다).
 * - 탐색으로 돌아갈 때 정확한 관측을 잃지 않도록, 작업구역이 검증된 상태에서는
 *   자산 참조도 함께 싣는다. 현황은 카탈로그와 대조해 모르는 참조를 공지만 두고
 *   조용히 다른 관측으로 바꾸지 않는다. 분석 선택(analysisId·currentWorkOrderId)은
 *   이 참조를 읽지 않으며, frozen 결과 입력도 대체하지 않는다.
 * - 범위 없이도 항상 실제 목적지를 가리킨다. 모르는 값이면 범위를 뺀다.
 */
export function siteTabHref(
  siteId: string,
  tab: string,
  current: { section?: string; epoch?: string },
  scope: SiteHeaderScope,
): string {
  const base = `/sites/${encodeURIComponent(siteId)}`;
  const workAreaId = scope.workAreaId;
  // 자산 참조는 같은 작업구역이 검증된 때만 싣는다 — 구역 없는 단독 참조는 버린다.
  const assetRef = workAreaId && scope.assetRef ? scope.assetRef : null;
  if (tab === "analysis") {
    const query = new URLSearchParams();
    if (workAreaId) query.set("workAreaId", workAreaId);
    if (assetRef) query.set("assetRef", assetRef);
    const search = query.toString();
    return search ? `${base}/analysis?${search}` : `${base}/analysis`;
  }
  if (tab === "materials") {
    const query = new URLSearchParams();
    if (workAreaId) query.set("workAreaId", workAreaId);
    if (assetRef) query.set("assetRef", assetRef);
    const search = query.toString();
    return search ? `${base}/spatial-assets?${search}` : `${base}/spatial-assets`;
  }
  const params = new URLSearchParams();
  if (tab !== "overview") params.set("section", tab);
  if (workAreaId) params.set("workAreaId", workAreaId);
  if (assetRef) params.set("assetRef", assetRef);
  if (current.epoch) params.set("epoch", current.epoch);
  const search = params.toString();
  return search ? `${base}?${search}` : base;
}
