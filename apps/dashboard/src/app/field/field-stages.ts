// 현장 화면(/field/{missionId})의 4단 구조 — 순수 도출.
//
// ── 이 파일이 지키는 규칙 ──────────────────────────────────────────────────
// ① **서버가 아는 사실만 말한다.** 서버는 비행 중 텔레메트리를 받지 않는다
//    (MISSION_EXECUTION_STATUSES 에 IN_FLIGHT 가 없는 것이 그 사실의 계약 표현이다).
//    그래서 "지금 날고 있다"는 어느 입력으로도 나오지 않는다.
// ② **수동 경로는 자동 상태와 무관하게 항상 문구를 갖는다.** 자동이 깨지는 상황은
//    정의상 통신 두절·장비 고장이고, 그때 "실패를 감지해야 나타나는 안내"는 나타나지
//    않는다. 그래서 `manual` 은 실패 여부를 보지 않는다.
// ③ **라벨을 새로 만들지 않는다.** 실행 상태·완료 판정의 한국어는 이미 SSOT 가 있다
//    (labels.ts / mission-labels.ts). 같은 상태를 화면마다 다른 말로 부르면 운영자가
//    매번 다시 읽는다.

import { COMPLETION_STATE_LABEL } from "@/app/missions/mission-labels";
import { MISSION_EXECUTION_STATUS_LABEL, type Tone } from "@/lib/core-api/labels";
import { formatKoreanDate } from "@/lib/datetime";
import type {
  CompletionState,
  MissionExecutionStatus,
  MissionExecutionView,
  MissionRecordResponse,
  SourceMediaBundleView,
} from "@/lib/core-api/types";

/**
 * 비행 결과 조회 결과를 이 화면이 필요한 만큼만 좁힌 것.
 *
 * `CoverageReportResult`(CoverageReportSection.tsx)를 그대로 받지 않는 이유는
 * 그쪽이 `CoreApiError` 인스턴스를 품고 있어서다 — 순수 도출 함수가 서버 전용
 * 모듈에 의존하면 이 판정을 시험할 때마다 그 모듈을 함께 끌고 와야 한다.
 */
export type FieldCoverageInput =
  | { kind: "reported"; completionState: CompletionState; recoveryRecommended: boolean }
  | { kind: "not-reported" }
  | { kind: "error" };

/**
 * 사진 묶음 조회 결과 — "아직 등록된 적 없음"과 "조회 실패"를 구분한다
 * (`FieldCoverageInput` 과 같은 이유). Core 는 등록된 적 없는 임무에 404 를 주고
 * (source-media.ts), 그것과 네트워크·서버 오류를 뭉개면 현장 통신이 잠깐 끊긴
 * 순간에도 "사진이 없다"는 문장이 뜬다 — 그 화면이 유도하는 행동은 불필요한
 * 재업로드다.
 */
export type FieldMediaInput =
  | { kind: "registered"; bundle: SourceMediaBundleView }
  | { kind: "not-registered" }
  | { kind: "error" };

export type FieldStageKey = "route" | "flight" | "media" | "result";

export interface FieldStage {
  key: FieldStageKey;
  /** 화면 왼쪽에 붙는 단계 이름. */
  title: string;
  /** 자동 경로가 지금 어디까지 갔는가 — 서버가 보고한 사실만. */
  auto: {
    label: string;
    detail: string;
    tone: Tone;
    /**
     * 이 배지가 대표하는 사실이 마지막으로 바뀐 시각(ISO). 그 사실이 없는 단계
     * (사진 회수·결과)는 이 필드를 채우지 않는다 — 없는 시각을 만들어내지 않는다.
     */
    updatedAt?: string | null;
  };
  /**
   * 수동 경로 안내. null 은 "이 단계에 수동 경로가 없다"이지 "지금은 필요 없다"가
   * 아니다 — 결과 단계(④)만 여기에 해당한다(현장에서 판정을 바꿀 수 없다).
   */
  manual: string | null;
}

export interface FieldStageInput {
  /** `contract` 면 내려받을 KMZ 자체가 없다(계약 단독 발급). */
  artifactKind: MissionRecordResponse["artifactKind"];
  /** null 이면 실행 상태 표면이 없는 조립이거나 조회 실패 — 아무것도 단정하지 않는다. */
  execution: MissionExecutionView | null;
  media: FieldMediaInput;
  coverage: FieldCoverageInput;
}

// ── ① 경로 확보 ────────────────────────────────────────────────────────────
//
// COMPLETED·ENDED_INCOMPLETE 를 "전달됨"으로 읽는 것은 추정이 아니라 계약이다 —
// 실행 생애주기(ADR-KSI-019 G2)는 ISSUED → DISPATCHED → ACTIVATED → 종료 순서라
// 종료 상태에 도달했다는 것 자체가 전달을 지났다는 뜻이다. 그래도 "확인했습니다"라고
// 말하지 않고 "지난 단계입니다"라고 말한다 — 우리가 아는 것은 순서지 그 시점의 사건이
// 아니다.
//
// 톤은 MissionLifecycle.tsx::deriveMissionStages 의 "실행" 단계와 같은
// MissionExecutionStatus 에 대해 항상 같은 색이어야 한다 — 이 표가 그쪽과 별도로
// 생기면서 한동안 갈렸다(같은 ACTIVATED 임무가 /missions 에서는 progress, /field 에서는
// positive 로 보이던 결함). 그 표가 이 제품에서 운영자가 먼저 보는 화면이라 이 표를
// 거기 맞춘다(field-stages.test.ts 의 교차 시험이 이 대응을 고정한다).
const ROUTE_DELIVERY: Record<MissionExecutionStatus, { detail: string; tone: Tone }> = {
  ISSUED: { detail: "아직 기체로 전달되지 않았습니다.", tone: "neutral" },
  DISPATCHED: { detail: "기체가 임무를 받아갔습니다.", tone: "progress" },
  ACTIVATED: { detail: "기체가 임무를 확인했습니다.", tone: "progress" },
  COMPLETED: { detail: "지난 단계입니다 — 비행 보고까지 도착했습니다.", tone: "positive" },
  ENDED_INCOMPLETE: { detail: "지난 단계입니다 — 비행이 완료되지 않고 끝났습니다.", tone: "warning" },
  // 배지 색은 /missions 기준(waiting→neutral)에 맞춘다. "비행하지 마세요"는 색이
  // 아니라 아래 detail 문장이 낸다 — 문장은 이 표 밖에서 항상 그대로 남는다.
  CANCELLED: { detail: "취소된 임무입니다. 비행하지 마세요.", tone: "neutral" },
};

// ── ② 비행 ─────────────────────────────────────────────────────────────────
//
// 종료 전 세 상태(ISSUED·DISPATCHED·ACTIVATED)가 전부 같은 문장인 것이 요점이다.
// 그 셋의 차이는 ①에서 이미 말했고, ②의 관점에서는 셋 다 **모르는 상태**로 똑같다.
const FLIGHT_REPORT: Record<MissionExecutionStatus, { label: string; detail: string; tone: Tone }> = {
  ISSUED: { label: "보고 없음", detail: "서버는 비행 중 상태를 받지 않습니다 — 완료 보고가 도착해야 알 수 있습니다.", tone: "neutral" },
  DISPATCHED: { label: "보고 없음", detail: "서버는 비행 중 상태를 받지 않습니다 — 완료 보고가 도착해야 알 수 있습니다.", tone: "neutral" },
  ACTIVATED: { label: "보고 없음", detail: "서버는 비행 중 상태를 받지 않습니다 — 완료 보고가 도착해야 알 수 있습니다.", tone: "neutral" },
  COMPLETED: { label: MISSION_EXECUTION_STATUS_LABEL.COMPLETED.label, detail: "기체가 완료를 보고했습니다.", tone: "positive" },
  ENDED_INCOMPLETE: { label: MISSION_EXECUTION_STATUS_LABEL.ENDED_INCOMPLETE.label, detail: "비행이 끝났지만 완료로 보고되지 않았습니다.", tone: "warning" },
  CANCELLED: { label: MISSION_EXECUTION_STATUS_LABEL.CANCELLED.label, detail: "취소된 임무입니다. 비행하지 마세요.", tone: "warning" },
};

const UNKNOWN_EXECUTION = {
  label: "확인 불가",
  detail: "서버가 이 임무의 실행 상태를 알지 못합니다.",
  tone: "neutral",
} as const;

function routeStage(input: FieldStageInput): FieldStage {
  const status = input.execution?.status ?? null;
  const auto =
    status === null
      ? { ...UNKNOWN_EXECUTION, detail: `${UNKNOWN_EXECUTION.detail} 아래 수동 경로를 쓰세요.`, updatedAt: null }
      : {
          label: MISSION_EXECUTION_STATUS_LABEL[status].label,
          detail: ROUTE_DELIVERY[status].detail,
          tone: ROUTE_DELIVERY[status].tone,
          // 이 배지가 대표하는 사실(직전 실행 상태 전이)이 언제 성립했는가 — 화면이
          // 상태 라벨만 내고 시각을 버리던 결함의 수정이다.
          updatedAt: input.execution?.updatedAt ?? null,
        };

  const manual =
    input.artifactKind === "pair"
      ? "KMZ 를 내려받아 조종기로 직접 옮길 수 있습니다. 자동 전달이 되지 않아도 이 경로는 항상 열려 있습니다."
      : "이 임무는 계약만 발급되어 내려받을 KMZ 파일이 없습니다.";

  return { key: "route", title: "경로 확보", auto, manual };
}

function flightStage(input: FieldStageInput): FieldStage {
  const status = input.execution?.status ?? null;
  return {
    key: "flight",
    title: "비행",
    auto: status === null ? { ...UNKNOWN_EXECUTION } : FLIGHT_REPORT[status],
    manual: "자동 시작이 없어도 Pilot 2 앱에서 이 임무를 직접 시작할 수 있습니다.",
  };
}

function mediaStage(input: FieldStageInput): FieldStage {
  const media = input.media;
  // "조회 실패"와 "아직 등록된 적 없음"을 여기서 갈라야 한다 — 뭉개면 Core 가 잠깐
  // 불안정한 순간에 이미 올린 사진이 "없다"고 나오고, 그 화면이 유도하는 행동은
  // 불필요한 재업로드다(coverage 쪽 resultStage 와 같은 원칙).
  const auto: FieldStage["auto"] =
    media.kind === "error"
      ? {
          label: "조회 실패",
          detail: "사진 등록 현황을 조회하지 못했습니다 — 이미 올린 사진이 있어도 지금은 확인할 수 없습니다.",
          tone: "warning",
        }
      : media.kind === "not-registered"
        ? { label: "없음", detail: "서버에 등록된 사진이 아직 없습니다.", tone: "neutral" }
        : media.bundle.status === "SEALED"
          ? { label: "봉인됨", detail: `${media.bundle.mediaCount}장이 봉인됐습니다 — 더 올릴 수 없습니다.`, tone: "positive" }
          : media.bundle.mediaCount > 0
            ? { label: "봉인 전", detail: `${media.bundle.mediaCount}장 등록됨 · 아직 봉인하지 않았습니다.`, tone: "progress" }
            : { label: "없음", detail: "묶음은 열렸지만 등록된 사진이 0장입니다.", tone: "neutral" };

  return {
    key: "media",
    title: "사진 회수",
    auto,
    // 이 한 줄이 이 단계에서 가장 중요한 사실이다. 위 숫자는 **두 경로의 합계**이고,
    // 서버는 어느 장이 자동으로 올라왔는지 구분해 보고하지 않는다. 그걸 말하지
    // 않으면 운영자는 저 숫자를 자동 회수 진행률로 읽고, 실제로는 자기가 올린
    // 장수를 보며 자동이 되고 있다고 믿게 된다.
    manual:
      "SD카드에서 직접 올릴 수 있습니다. 위 장수는 자동 회수와 수동 업로드를 합친 값입니다 — 서버는 두 경로를 구분해 보고하지 않습니다.",
  };
}

function resultStage(input: FieldStageInput): FieldStage {
  const coverage = input.coverage;
  if (coverage.kind === "not-reported") {
    return {
      key: "result",
      title: "결과",
      auto: { label: "보고 없음", detail: "비행 결과 보고가 아직 도착하지 않았습니다.", tone: "neutral" },
      manual: null,
    };
  }
  if (coverage.kind === "error") {
    return {
      key: "result",
      title: "결과",
      auto: { label: "조회 실패", detail: "비행 결과를 조회하지 못했습니다.", tone: "warning" },
      manual: null,
    };
  }

  const completion = COMPLETION_STATE_LABEL[coverage.completionState];
  // 재관측 권고는 completionState 가 COMPLETED 여도 붙을 수 있다(사유 있는 미관찰이
  // 남은 경우). 그때 초록색 하나만 보이면 "다 끝났다"로 읽히므로 색을 한 단계 내린다.
  const tone: Tone =
    coverage.recoveryRecommended && completion.tone === "positive" ? "caution" : completion.tone;
  return {
    key: "result",
    title: "결과",
    auto: {
      label: completion.label,
      detail: coverage.recoveryRecommended
        ? "재관측이 권고됩니다 — 같은 구역으로 임무를 다시 발급하세요. 자동으로 재발급되지 않습니다."
        : "서버가 판정한 결과입니다.",
      tone,
    },
    manual: null,
  };
}

/** 현장 화면 4단 — 순서가 곧 현장에서 일이 벌어지는 순서다. */
export function deriveFieldStages(input: FieldStageInput): FieldStage[] {
  return [routeStage(input), flightStage(input), mediaStage(input), resultStage(input)];
}

/**
 * [임무 시작] 버튼의 상태.
 *
 * `enabled` 의 타입이 `false` 리터럴인 것은 의도다 — 이번 라운드에 **켜지는 경로가
 * 아예 없다**. 기체에 임무를 올리고 시작시키는 호출부가 존재하지 않고(안전 개방
 * S0), 그 개방은 코드 한 줄이 아니라 단계별 게이트로 이뤄진다. 타입이 true 를 허용하면
 * 언젠가 조건 하나가 늘어나며 조용히 켜질 수 있다.
 *
 * 버튼을 아예 안 그리지 않고 **비활성 + 사유 문장**으로 남기는 이유: 현장에서
 * "왜 자동 시작이 없나"는 반드시 나오는 질문이고, 화면에 자리가 없으면 그 답이
 * 구두 전달에만 남는다.
 */
export interface FlightStartControl {
  enabled: false;
  reason: string;
}

export function deriveFlightStart(input: { execution: MissionExecutionView | null }): FlightStartControl {
  if (input.execution?.status === "CANCELLED") {
    return { enabled: false, reason: "취소된 임무입니다 — 시작할 수 없습니다." };
  }
  return {
    enabled: false,
    reason:
      "자동 시작 경로가 아직 없습니다 — 기체에 임무를 올리고 시작시키는 연결이 만들어지지 않았습니다. 비행은 Pilot 2 앱에서 직접 시작하세요.",
  };
}

// ── 목록 화면(/field) ──────────────────────────────────────────────────────

export interface FieldMissionGroups {
  /** 오늘(서울 기준 달력 날짜) 발급된 임무 — 최신 먼저. */
  today: MissionRecordResponse[];
  /** 그 앞의 임무들 — 최신 먼저, `limit` 건까지. */
  earlier: MissionRecordResponse[];
  /** `earlier` 에서 잘려나간 건수. 0 이 아니면 화면이 그 사실을 밝힌다. */
  hiddenCount: number;
}

/**
 * 현장에서 열었을 때 첫 화면에 무엇이 있어야 하는가.
 *
 * "오늘"의 기준은 **서울 달력 날짜**다 — 서버 컨테이너가 어느 시간대로 뜨든
 * 현장은 한국이다(`formatKoreanDate` 가 그 규율의 정본이고 여기서 다시 만들지 않는다).
 *
 * 오늘 것이 없다고 빈 화면을 주지 않는다 — 임무는 전날 저녁에 발급되고 다음 날
 * 아침에 비행하는 일이 흔하다. 그래서 `earlier` 를 함께 내고, 잘라낸 건수를
 * 숨기지 않는다(무엇이 안 보이는지 모르는 목록은 현장에서 신뢰를 잃는다).
 */
export function groupFieldMissions(
  missions: readonly MissionRecordResponse[],
  nowIso: string,
  limit = 12,
): FieldMissionGroups {
  const todayLabel = formatKoreanDate(nowIso);
  const sorted = [...missions].sort((a, b) => b.issuedAt.localeCompare(a.issuedAt));
  const today = sorted.filter((mission) => formatKoreanDate(mission.issuedAt) === todayLabel);
  const rest = sorted.filter((mission) => formatKoreanDate(mission.issuedAt) !== todayLabel);
  return { today, earlier: rest.slice(0, limit), hiddenCount: Math.max(0, rest.length - limit) };
}
