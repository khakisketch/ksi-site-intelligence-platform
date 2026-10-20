import type { SiteStatus } from "./types";

/**
 * 현장 진행 단계 — "이 현장이 어디까지 왔나"를 한 줄로 그리기 위한 순수 판정.
 *
 * ── 왜 이 파일이 따로 있나 ───────────────────────────────────────────────
 * `labels.ts` 는 "상태 → 낱말"의 정본이다. 여기 있는 것은 낱말이 아니라 **순서**다:
 * 어떤 상태가 어떤 상태보다 앞이라는 주장은 도메인 전이표에서 와야 하고, 화면이
 * 임의로 정하면 안 된다. 아래 본선은 `ksi_domain.enums._ALLOWED_SITE_TRANSITIONS`
 * 의 간선을 그대로 따라간 것이다:
 *
 *   UNMAPPED → BASELINE_MAPPING → MODEL_PROCESSING → MODEL_VALIDATION
 *            → PROVISIONAL_AUTONOMY → PATROL_READY → PATROL_ACTIVE
 *
 * 그 표의 주석이 못박은 대로 `PATROL_READY` 로 들어오는 간선은
 * `PROVISIONAL_AUTONOMY`·`PATROL_ACTIVE` 둘뿐이다(품질 검증 우회 금지). 그래서
 * 본선은 지름길이 없는 한 줄이고, 막대 하나가 곧 한 단계다.
 *
 * ── 본선 밖 상태를 본선 위에 억지로 놓지 않는다 ──────────────────────────
 * `MODEL_STALE`·`REMAP_REQUIRED` 는 **뒤로 돌아간** 상태다. 진행률로 환산해
 * "80% 왔음"이라 그리면 앞으로 가는 중이라는 거짓말이 된다 — 대신 *다시 시작할
 * 지점*을 되돌림 표시로 찍는다(전이표가 정한 복귀 입구: 모델 최신도 낮음은
 * 모델 처리부터, 재매핑 필요는 초기 매핑부터).
 *
 * `SUSPENDED` 는 본선 어디에도 없다 — 전이표가 이 상태에서 나가는 정적 간선을
 * 아예 두지 않고, 복귀는 저장소가 기억한 직전 상태로만 간다. 위치를 아는 척하지
 * 않고 전 구간을 '모름'으로 비운다.
 */
export const SITE_PROGRESS_STAGES: readonly {
  status: SiteStatus;
  /** 막대에 붙는 접근성 이름 — 화면에는 막대만 보이므로 읽어주는 쪽엔 이 말이 간다. */
  label: string;
}[] = [
  // 외부 관측 유무는 이 과거 취득 상태에서 추론하지 않는다. 아래 전이 순서는
  // 보존하되, 최초 단계는 확인되는 현장 등록 사실만 말한다(ADR-KSI-039).
  { status: "UNMAPPED", label: "현장 등록" },
  { status: "BASELINE_MAPPING", label: "초기 매핑" },
  { status: "MODEL_PROCESSING", label: "모델 처리" },
  { status: "MODEL_VALIDATION", label: "모델 검증" },
  { status: "PROVISIONAL_AUTONOMY", label: "임시 자율운영" },
  { status: "PATROL_READY", label: "순찰 준비" },
  { status: "PATROL_ACTIVE", label: "순찰 중" },
];

/** done=지나옴 · current=지금 여기 · rework=여기서 다시 · todo=아직 · unknown=위치 모름 */
export type SiteProgressCell = "done" | "current" | "rework" | "todo" | "unknown";

export interface SiteProgress {
  cells: SiteProgressCell[];
  /** 막대만으로는 못 하는 말 — 되돌아갔다·멈췄다 같은 사실. 본선 위면 빈 문자열. */
  note: string;
}

/** 본선 밖 상태가 **다시 시작하는 지점**(전이표의 복귀 입구). */
const REWORK_ENTRY: Partial<Record<SiteStatus, SiteStatus>> = {
  MODEL_STALE: "MODEL_PROCESSING",
  REMAP_REQUIRED: "BASELINE_MAPPING",
};

const REWORK_NOTE: Partial<Record<SiteStatus, string>> = {
  MODEL_STALE: "모델 처리부터 다시",
  REMAP_REQUIRED: "초기 매핑부터 다시",
};

export function siteProgress(status: SiteStatus): SiteProgress {
  const mainlineIndex = SITE_PROGRESS_STAGES.findIndex((stage) => stage.status === status);
  if (mainlineIndex >= 0) {
    return {
      cells: SITE_PROGRESS_STAGES.map((_stage, index) =>
        index < mainlineIndex ? "done" : index === mainlineIndex ? "current" : "todo",
      ),
      note: "",
    };
  }

  const entry = REWORK_ENTRY[status];
  if (entry) {
    const entryIndex = SITE_PROGRESS_STAGES.findIndex((stage) => stage.status === entry);
    return {
      cells: SITE_PROGRESS_STAGES.map((_stage, index) =>
        index < entryIndex ? "done" : index === entryIndex ? "rework" : "todo",
      ),
      note: REWORK_NOTE[status] ?? "",
    };
  }

  // SUSPENDED — 그리고 미래에 추가될 본선 밖 상태. 위치를 지어내지 않는다.
  return {
    cells: SITE_PROGRESS_STAGES.map(() => "unknown"),
    note: status === "SUSPENDED" ? "재개하면 직전 단계부터" : "진행 단계를 알 수 없음",
  };
}

/**
 * 그 상태에서 **사람이 다음에 할 일** 한 줄.
 *
 * 상태값을 다른 말로 바꾼 것이 아니라, 그 상태가 무엇을 기다리는지를 쓴다 —
 * "모델 처리 중"(상태)과 "처리 결과를 기다리는 중"(할 일)은 다른 문장이고, 목록
 * 에서 유용한 쪽은 뒤다. 링크가 있는 것은 **화면에서 바로 시작할 수 있는 일**뿐이다:
 * 나머지는 기다림이라 갈 곳이 현장 상세 하나뿐이고, 그때는 `href` 를 주지 않는다
 * (행 전체가 이미 현장으로 간다 — 같은 곳으로 가는 버튼을 하나 더 두지 않는다).
 */
export interface SiteNextAction {
  label: string;
  /** 조사 계획처럼 지금 시작할 수 있는 일이면 그 경로. 기다림이면 null. */
  survey: boolean;
  /** 지금 사람이 움직여야 하는 일인가 — 기다림과 구분해 강조한다. */
  actionable: boolean;
}

const NEXT_ACTION: Record<SiteStatus, SiteNextAction> = {
  UNMAPPED: { label: "자료·작업 확인", survey: false, actionable: false },
  REMAP_REQUIRED: { label: "재조사 계획", survey: true, actionable: true },
  MODEL_STALE: { label: "재조사 검토", survey: true, actionable: true },
  BASELINE_MAPPING: { label: "촬영·업로드 대기", survey: false, actionable: false },
  MODEL_PROCESSING: { label: "처리 결과 대기", survey: false, actionable: false },
  MODEL_VALIDATION: { label: "품질 검증 확인", survey: false, actionable: true },
  PROVISIONAL_AUTONOMY: { label: "순찰 승인 검토", survey: false, actionable: true },
  PATROL_READY: { label: "순찰 임무 발급", survey: true, actionable: true },
  PATROL_ACTIVE: { label: "순찰 상황 확인", survey: false, actionable: false },
  SUSPENDED: { label: "운영 재개 검토", survey: false, actionable: true },
};

export function siteNextAction(status: SiteStatus): SiteNextAction {
  return NEXT_ACTION[status];
}

// ── 상태 묶음 ──────────────────────────────────────────────────────────────
//
// 10개 상태를 낱개로 거르는 것은 이 상태표를 외운 사람만 쓸 수 있다. 운영자가 실제로
// 묻는 것은 넷이다: 내가 손대야 하나 · 기다리면 되나 · 날릴 수 있나 · 멈춰 있나.

/**
 * "순찰 가능"은 **화이트리스트로만** 정의한다.
 *
 * `전체 − 순찰불가`로 빼서 구하면 준비 단계(BASELINE_MAPPING·MODEL_PROCESSING·
 * MODEL_VALIDATION)와 모델 노후(MODEL_STALE), 심지어 **운영 중단(SUSPENDED)** 까지
 * 순찰 가능으로 세어진다. 운영을 정식으로 멈춘 현장을 현황판이 "순찰 가능"이라 말하는
 * 건 그냥 거짓말이다. 뺄셈은 새 상태가 추가될 때도 조용히 '가능' 쪽으로 흡수한다 —
 * 안전 화면의 파생 지표는 열거를 늘리는 쪽이 틀렸을 때 눈에 띈다.
 *
 * 홈의 지표 타일과 현장 목록의 묶음 필터가 **같은 집합**을 봐야 한다 — 두 화면이 서로
 * 다른 수를 말하면 어느 쪽도 못 믿는다.
 */
export const PATROLLABLE_SITE_STATUSES: ReadonlySet<SiteStatus> = new Set<SiteStatus>([
  "PROVISIONAL_AUTONOMY",
  "PATROL_READY",
  "PATROL_ACTIVE",
]);

/** 등록 상태만으로 외부 자료 부재나 조치 필요를 추론하지 않는다. */
export const ATTENTION_SITE_STATUSES: ReadonlySet<SiteStatus> = new Set<SiteStatus>([
  "REMAP_REQUIRED",
  "MODEL_STALE",
]);

/** 시스템이 진행 중이라 사람이 기다리는 상태. */
export const PREPARING_SITE_STATUSES: ReadonlySet<SiteStatus> = new Set<SiteStatus>([
  "BASELINE_MAPPING",
  "MODEL_PROCESSING",
  "MODEL_VALIDATION",
]);

/** External observations do not advance the historical acquisition lifecycle. */
export const REGISTERED_SITE_STATUSES: ReadonlySet<SiteStatus> = new Set<SiteStatus>(["UNMAPPED"]);

export const SITE_GROUPS = [
  { key: "all", label: "전체", statuses: null },
  { key: "registered", label: "등록됨", statuses: REGISTERED_SITE_STATUSES },
  { key: "attention", label: "확인 필요", statuses: ATTENTION_SITE_STATUSES },
  { key: "preparing", label: "준비 중", statuses: PREPARING_SITE_STATUSES },
  { key: "patrol", label: "순찰 가능", statuses: PATROLLABLE_SITE_STATUSES },
  { key: "suspended", label: "운영 중단", statuses: new Set<SiteStatus>(["SUSPENDED"]) },
] as const;

export type SiteGroupKey = (typeof SITE_GROUPS)[number]["key"];

/** URL 의 묶음 값은 사용자가 편집할 수 있다 — 아는 값만 받고 나머지는 전체로 되돌린다. */
export function normalizeSiteGroup(raw: string | null | undefined): SiteGroupKey {
  const hit = SITE_GROUPS.find((group) => group.key === raw);
  return hit ? hit.key : "all";
}

/** 그 묶음이 포함하는 상태 집합. `null` 은 "거르지 않음"이다. */
export function siteGroupStatuses(key: SiteGroupKey): ReadonlySet<SiteStatus> | null {
  return SITE_GROUPS.find((group) => group.key === key)?.statuses ?? null;
}

/**
 * 다섯 묶음이 10개 상태를 **빠짐없이 한 번씩** 덮는지 — 새 상태가 생겼을 때 어느
 * 묶음에도 안 들어가 목록에서 조용히 사라지는 일을 막는다(테스트가 이 함수를 쓴다).
 */
export function siteGroupCoverage(all: readonly SiteStatus[]): {
  uncovered: SiteStatus[];
  duplicated: SiteStatus[];
} {
  const counts = new Map<SiteStatus, number>(all.map((status) => [status, 0]));
  for (const group of SITE_GROUPS) {
    if (!group.statuses) continue;
    for (const status of group.statuses) {
      counts.set(status, (counts.get(status) ?? 0) + 1);
    }
  }
  return {
    uncovered: [...counts].filter(([, n]) => n === 0).map(([status]) => status),
    duplicated: [...counts].filter(([, n]) => n > 1).map(([status]) => status),
  };
}
