"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { ErrorState } from "@/components/ui/ErrorState";
import { WizardShell } from "@/components/wizard/WizardShell";
import { useDraftState } from "@/hooks/useDraftState";
import { isConvexPolygon } from "@/lib/geometry";
import type {
  AoiVertex,
  MissionPlanRequest,
  MissionPlanResponse,
  MissionType,
  SiteView,
} from "@/lib/core-api/types";
import { formatCoverageRatio } from "@/app/missions/format";

// PRD §7.4 5스텝 라벨 그대로 — UX 목표 §2 "5클릭 = 예산 그 자체".
const STEP_LABELS = ["대상", "목적", "조사 수준", "자동 계획 검토", "전송 및 승인"];

type RoutePattern = "lawnmower" | "perimeter";

type TargetValue = "FULL_SITE" | "ZONE" | "BUILDING" | "FACADE_ROOF" | "EQUIPMENT" | "YARD_PATHWAY";

// "현장 전체"만 실동작 — 나머지는 자리만 유지하고 "준비 중"으로 정직하게 표시한다
// (UX 목표 §6/INV-040과 같은 정신 — 링크를 숨기지 않고 상태를 밝힌다).
const TARGET_OPTIONS: Array<{ value: TargetValue; label: string; enabled: boolean }> = [
  { value: "FULL_SITE", label: "현장 전체", enabled: true },
  { value: "ZONE", label: "구역", enabled: false },
  { value: "BUILDING", label: "건물", enabled: false },
  { value: "FACADE_ROOF", label: "외벽·옥상", enabled: false },
  { value: "EQUIPMENT", label: "설비", enabled: false },
  { value: "YARD_PATHWAY", label: "야적장·통로", enabled: false },
];

interface PurposeOption {
  key: string;
  label: string;
  missionType: MissionType | null;
  pattern: RoutePattern | null;
  enabled: boolean;
}

// 백엔드 미션타입→경로패턴 제약(services/core/src/ksi_core/mission_plans.py) 밖의 조합은
// 애초에 선택하지 못하게 막는다 — 허용되지 않는 조합을 시도해보고서야 422 를 보여주지 않는다
// (CLAUDE.md 지시 §7 그대로, 재해석 금지).
//
// BASELINE_MAPPING 은 이 목록의 나머지 옵션과 달리 항상 활성이 아니다 — buildPurposeOptions()
// 가 site.status==="UNMAPPED" 일 때만 켠다(risk dashboard-wizard-rbac-mismatch 해소 — 현장
// 등록 Wizard에서 분리된 baseline 임무 발급을 이 화면이 대신한다. SITES_WRITE 만 가진
// role은 현장만 등록하고, MISSIONS_ISSUE 를 가진 role이 나중에 여기서 발급한다).
function buildPurposeOptions(siteIsUnmapped: boolean): PurposeOption[] {
  return [
    {
      key: "BASELINE_MAPPING",
      label: "초기 매핑(베이스라인)",
      missionType: "BASELINE_MAPPING",
      pattern: "lawnmower",
      enabled: siteIsUnmapped,
    },
    {
      key: "SAFETY_RISK",
      label: "안전 위험",
      missionType: "AUTONOMOUS_PATROL",
      pattern: "perimeter",
      enabled: true,
    },
    {
      key: "SPATIAL_REFRESH",
      label: "공간 모델 갱신",
      missionType: "SPATIAL_REFRESH",
      pattern: "lawnmower",
      enabled: true,
    },
    {
      key: "PROGRESS_CAPTURE",
      label: "공정 변화",
      missionType: "PROGRESS_CAPTURE",
      pattern: "lawnmower",
      enabled: true,
    },
    {
      key: "INCIDENT_SURVEY",
      label: "사고조사",
      missionType: "INCIDENT_SURVEY",
      pattern: "perimeter",
      enabled: true,
    },
    {
      key: "UNIFIED_SITE_SURVEY",
      label: "전체 조사",
      missionType: "UNIFIED_SITE_SURVEY",
      pattern: "lawnmower",
      enabled: true,
    },
    {
      key: "ASSET_INSPECTION",
      label: "구조물 결함",
      missionType: "ASSET_INSPECTION",
      pattern: "lawnmower",
      enabled: false,
    },
    {
      key: "EQUIPMENT_MATERIAL",
      label: "장비·자재 현황",
      missionType: null,
      pattern: null,
      enabled: false,
    },
  ];
}

// 서버가 고정한 규제 고도 상한(항공안전법 일반 비행제한 고도). 계약의
// maxAltitudeM 이 이 값을 넘으면 서버가 422 로 거부하므로, 여기서 먼저 막아
// 사용자가 8단계를 다 채우고 나서야 실패를 보는 일을 없앤다.
const MAX_ALTITUDE_M = 150;
// 계약 봉투는 비행 고도보다 10m 여유를 둔다 — 그 여유까지 상한 안이어야 한다.
const MAX_FLIGHT_ALTITUDE_M = MAX_ALTITUDE_M - 10;

type SurveyLevel = "FAST" | "STANDARD" | "PRECISE";

// captureIntervalM 은 스캔선을 따라 촬영하는 간격이다. 값이 빠지면 스캔선당
// 사진이 양 끝 2장뿐이라 진행방향 겹침이 0 이 되고, 비행은 정상으로 끝나는데
// 지도·3D 산출물만 나오지 않는다 — 그래서 서버가 아예 발급을 거부한다.
// 세 수준 모두 스캔선 간격보다 촘촘하게 둔다(진행방향 겹침을 더 크게).
const LEVEL_PRESETS: Record<
  SurveyLevel,
  { label: string; spacingM: number; captureIntervalM: number; autoFlightSpeedMs: number }
> = {
  FAST: { label: "빠른", spacingM: 30, captureIntervalM: 22, autoFlightSpeedMs: 8 },
  STANDARD: { label: "표준", spacingM: 20, captureIntervalM: 15, autoFlightSpeedMs: 5 },
  PRECISE: { label: "정밀", spacingM: 10, captureIntervalM: 7, autoFlightSpeedMs: 3 },
};

type NumericDraftKey =
  | "altitudeM"
  | "takeoffSecurityHeightM"
  | "globalTransitionalSpeedMs"
  | "droneEnumValue"
  | "droneSubEnumValue"
  | "payloadEnumValue";

interface SurveyDraft {
  step: number;
  target: TargetValue | null;
  aoi: AoiVertex[];
  missionType: MissionType | null;
  // 재시도/새로고침에도 안정적으로 재사용해야 서버 멱등성(같은 missionId+같은 요청)이
  // 실제로 작동한다 — 매번 새로 생성하면 재시도마다 별개의 서명 계약이 발급된다.
  missionId: string | null;
  level: SurveyLevel | null;
  altitudeM: number;
  takeoffSecurityHeightM: number;
  globalTransitionalSpeedMs: number;
  droneEnumValue: number;
  droneSubEnumValue: number;
  payloadEnumValue: number;
  viewpointPolicyId: string;
  riskPolicyPackId: string;
  fallbackPolicyId: string;
  capturePolicyId: string;
}

// 고급 설정 기본값 — 백엔드에 해석 레지스트리가 없어 서버가 추측하지 않는 값들이다
// (UX 목표 §7: "실기 검증 전 원시값" 그대로 명시 텍스트 입력으로 노출).
const INITIAL_DRAFT: SurveyDraft = {
  step: 0,
  target: null,
  aoi: [],
  missionType: null,
  missionId: null,
  level: null,
  altitudeM: 40,
  takeoffSecurityHeightM: 20,
  globalTransitionalSpeedMs: 10,
  droneEnumValue: 99,
  droneSubEnumValue: 0,
  payloadEnumValue: 65534,
  viewpointPolicyId: "default-viewpoint-policy",
  riskPolicyPackId: "default-risk-policy",
  fallbackPolicyId: "default-fallback-policy",
  capturePolicyId: "default-capture-policy",
};

type SubmitStatus = "idle" | "pending" | "success" | "error";

const REVIEW_STEP = 3;
const SUBMIT_STEP = 4;

export function SurveyWizard({ site }: { site: SiteView }) {
  const router = useRouter();
  const [draft, setDraft, clearDraft] = useDraftState<SurveyDraft>(
    `ksi-wizard-survey-${site.siteId}`,
    INITIAL_DRAFT,
  );
  const [status, setStatus] = useState<SubmitStatus>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [result, setResult] = useState<MissionPlanResponse | null>(null);

  const purposeOptions = buildPurposeOptions(site.status === "UNMAPPED");
  const selectedPurpose = purposeOptions.find(
    (opt) => opt.enabled && opt.missionType === draft.missionType,
  );
  const routePattern: RoutePattern | null = selectedPurpose?.pattern ?? null;

  function update(patch: Partial<SurveyDraft>) {
    setDraft({ ...draft, ...patch });
  }

  function updateNumber(key: NumericDraftKey, raw: string) {
    const value = Number(raw);
    if (!Number.isNaN(value)) setDraft({ ...draft, [key]: value });
  }

  function goTo(step: number) {
    setDraft({ ...draft, step });
  }

  async function submitPlan() {
    if (!draft.missionType || !routePattern) return;
    setStatus("pending");
    setErrorMessage(null);
    // missionId 는 최초 1회만 생성해 draft(sessionStorage)에 고정한다 — "다시 시도"·새로고침
    // 재진입 모두 같은 값을 재사용해야 서버 멱등성(같은 missionId+같은 요청→200 재반환)이
    // 실제로 작동하고, 재시도마다 별개의 서명 계약이 중복 발급되지 않는다. 새로고침에도
    // 살아남아야 해서 useRef(SiteRegistrationWizard.tsx 패턴)가 아니라 draft에 저장한다.
    // eslint-disable-next-line react-hooks/purity -- submitPlan은 렌더 중이 아니라 두 useEffect(스텝 진입·재시도 버튼)에서만 호출된다. Date.now()는 그 호출 시점에만 평가되고 렌더 출력에 영향을 주지 않는다.
    const missionId = draft.missionId ?? `${site.siteId}-survey-${Date.now()}`;
    if (!draft.missionId) setDraft({ ...draft, missionId });
    try {
      const payload: MissionPlanRequest = {
        contract: {
          missionId,
          siteId: site.siteId,
          missionType: draft.missionType,
          siteFrame: site.siteFrame,
          flightEnvelope: {
            // 빈 배열은 "허용 구역 없음"으로 해석돼 422 EMPTY_ALLOWED_VOLUMES 로 거부된다
            // (packages/mission-planning coverage.py) — AOI 전체를 덮는 단일 허용 구역
            // 라벨을 기본값으로 선언한다(SiteRegistrationWizard.tsx와 동일 규약).
            allowedVolumes: ["site-boundary"],
            excludedVolumes: [],
            minAltitudeM: 0,
            maxAltitudeM: Math.max(draft.altitudeM + 10, 30),
          },
          objectives: [selectedPurpose?.label ?? ""],
          viewpointPolicyId: draft.viewpointPolicyId,
          riskPolicyPackId: draft.riskPolicyPackId,
          fallbackPolicyId: draft.fallbackPolicyId,
          capturePolicyId: draft.capturePolicyId,
        },
        aoi: { vertices: draft.aoi },
        route: {
          altitudeM: draft.altitudeM,
          ...(routePattern === "lawnmower" && draft.level
            ? {
                spacingM: LEVEL_PRESETS[draft.level].spacingM,
                captureIntervalM: LEVEL_PRESETS[draft.level].captureIntervalM,
              }
            : {}),
        },
        drone: {
          droneEnumValue: draft.droneEnumValue,
          droneSubEnumValue: draft.droneSubEnumValue,
          payloadEnumValue: draft.payloadEnumValue,
        },
        wayline: {
          autoFlightSpeedMs: draft.level ? LEVEL_PRESETS[draft.level].autoFlightSpeedMs : 5,
          takeoffSecurityHeightM: draft.takeoffSecurityHeightM,
          globalTransitionalSpeedMs: draft.globalTransitionalSpeedMs,
        },
      };

      const response = await fetch("/api/mission-plans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        setStatus("error");
        setErrorMessage(
          (body && typeof body.message === "string" && body.message) ||
            "요청을 처리하지 못했습니다.",
        );
        return;
      }
      setResult(body as MissionPlanResponse);
      setStatus("success");
      // 성공 후 draft 를 지운다 — 새로고침해도 이미 발급된 조사를 다시 제출하지 않는다.
      clearDraft();
      // 셸(사이드바 임무 배지)은 layout 에 있어 클라이언트 네비게이션으로는 다시 그려지지
      // 않는다 — 방금 발급한 임무가 반영되도록 서버 렌더를 한 번 요청한다.
      router.refresh();
    } catch {
      setStatus("error");
      setErrorMessage("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    }
  }

  // Step 5 진입 시 자동으로 발급을 시도한다(CLAUDE.md 지시 — "진입 시 또는 버튼 클릭 시").
  useEffect(() => {
    if (draft.step === SUBMIT_STEP && status === "idle") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 외부 API(mission-plans) 호출 결과로 갱신, 렌더 중 계산 불가
      void submitPlan();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- step 진입 시 1회만 트리거한다.
  }, [draft.step]);

  let onBack: (() => void) | undefined;
  if (draft.step > 0 && draft.step < SUBMIT_STEP) {
    onBack = () => goTo(draft.step - 1);
  } else if (draft.step === SUBMIT_STEP && status === "error") {
    onBack = () => {
      // 검토 단계로 돌아가 파라미터를 바꿀 수 있게 하므로 missionId 를 놓아준다 —
      // 그대로 두면 바뀐 payload 로 재제출할 때 같은 missionId 가 MISSION_ID_CONFLICT
      // 로 영구 고착된다(독립 재검토 2차 C-2). "다시 시도"(같은 화면의 버튼, 여기를
      // 안 거침)는 계속 같은 missionId 를 재사용해 서버 멱등성을 그대로 누린다.
      setDraft({ ...draft, step: REVIEW_STEP, missionId: null });
      setStatus("idle");
      setErrorMessage(null);
    };
  }

  let onNext: () => void = () => {};
  let nextDisabled = false;
  let nextLabel: string | undefined;
  let nextPending = false;

  switch (draft.step) {
    case 0:
      nextDisabled = !(draft.target === "FULL_SITE" && draft.aoi.length >= 3);
      onNext = () => goTo(1);
      break;
    case 1:
      // lawnmower(매핑) 패턴은 볼록 AOI 에서만 서버가 발급한다(coverage.py NON_CONVEX_AOI) —
      // 이미 그린 외곽이 오목한데 매핑 계열 목적을 고르면 5단계에서 반드시 실패하므로 미리 막는다.
      nextDisabled = !selectedPurpose || (routePattern === "lawnmower" && !isConvexPolygon(draft.aoi));
      onNext = () => goTo(2);
      break;
    case 2:
      // 고도 상한 초과는 서버가 422 로 거부한다(규제 상한, 요청으로 못 바꾼다) —
      // 여기서 막지 않으면 오류 문구는 떠 있는데 계속 진행되고, 마지막 발급 단계에
      // 가서야 실패한다(문구만 있고 일은 안 막는 상태).
      nextDisabled = !draft.level || draft.altitudeM > MAX_FLIGHT_ALTITUDE_M;
      onNext = () => goTo(3);
      break;
    case REVIEW_STEP:
      // "계약 발급" — 마이크로카피 SSOT(UX 목표 §4.5), "제출"·"전송" 같은 막연한 동사 금지.
      nextLabel = "계약 발급";
      onNext = () => goTo(SUBMIT_STEP);
      break;
    case SUBMIT_STEP:
      nextPending = status === "pending";
      if (status === "success") {
        nextLabel = "현장 상세로 이동";
        onNext = () => router.push(`/sites/${encodeURIComponent(site.siteId)}`);
      } else if (status === "error") {
        nextLabel = "다시 시도";
        onNext = () => void submitPlan();
      } else {
        nextDisabled = true;
      }
      break;
    default:
      break;
  }

  let stepContent: React.ReactNode = null;

  if (draft.step === 0) {
    stepContent = (
      <>
        <fieldset className="flex flex-col gap-2 sm:col-span-2">
          <legend className="text-[12.5px] font-semibold break-keep text-ink-1">
            조사 대상을 선택하세요
          </legend>
          {TARGET_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={`tap-target flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm break-keep ${
                opt.enabled
                  ? draft.target === opt.value
                    ? "border-accent bg-accent-tint"
                    : "border-line-strong bg-surface"
                  : "border-line bg-surface text-ink-muted"
              }`}
            >
              <span className="flex items-center gap-2">
                <input
                  type="radio"
                  name="survey-target"
                  value={opt.value}
                  disabled={!opt.enabled}
                  checked={draft.target === opt.value}
                  onChange={() => update({ target: opt.value })}
                />
                {opt.label}
              </span>
              {!opt.enabled && <span className="text-xs text-ink-muted">준비 중</span>}
            </label>
          ))}
        </fieldset>

        {draft.target === "FULL_SITE" && (
          <div className="flex flex-col gap-2 sm:col-span-2">
            <p className="text-sm break-keep text-ink-2">
              조사할 영역의 경계를 지도에 그려주세요(최소 3개 꼭짓점). 현장 경계는 서버에
              저장돼 있지 않아 매번 새로 그려야 합니다.
            </p>
            <AoiPolygonMap value={draft.aoi} onChange={(vertices) => update({ aoi: vertices })} />
            <p className="text-xs text-ink-muted">
              현재 꼭짓점 {draft.aoi.length}개{draft.aoi.length < 3 ? " (최소 3개 필요)" : ""}
            </p>
          </div>
        )}
      </>
    );
  } else if (draft.step === 1) {
    stepContent = (
      <fieldset className="flex flex-col gap-2 sm:col-span-2">
        <legend className="text-[12.5px] font-semibold break-keep text-ink-1">
          현장조사의 목적을 선택하세요
        </legend>
        {purposeOptions.map((opt) => {
          const checked = opt.enabled && draft.missionType === opt.missionType;
          return (
            <label
              key={opt.key}
              className={`tap-target flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm break-keep ${
                opt.enabled
                  ? checked
                    ? "border-accent bg-accent-tint"
                    : "border-line-strong bg-surface"
                  : "border-line bg-surface text-ink-muted"
              }`}
            >
              <span className="flex items-center gap-2">
                <input
                  type="radio"
                  name="survey-purpose"
                  disabled={!opt.enabled}
                  checked={checked}
                  onChange={() =>
                    opt.missionType && update({ missionType: opt.missionType, level: null })
                  }
                />
                {opt.label}
              </span>
              {!opt.enabled && <span className="text-xs text-ink-muted">준비 중</span>}
            </label>
          );
        })}
        {routePattern === "lawnmower" && !isConvexPolygon(draft.aoi) && (
          <p className="text-sm break-keep text-high-ink">
            이 목적은 매핑(격자) 경로를 사용하는데, 1단계에서 그린 외곽이 볼록하지 않습니다.
            이전으로 돌아가 다시 그리세요.
          </p>
        )}
      </fieldset>
    );
  } else if (draft.step === 2) {
    stepContent = (
      <div className="flex flex-col gap-4 sm:col-span-2">
        <div className="flex gap-2">
          {(Object.keys(LEVEL_PRESETS) as SurveyLevel[]).map((key) => (
            <button
              type="button"
              key={key}
              onClick={() => update({ level: key })}
              className={`btn flex-1 ${draft.level === key ? "btn-primary" : ""}`}
            >
              {LEVEL_PRESETS[key].label}
            </button>
          ))}
        </div>

        {draft.level && (
          <dl className="flex flex-col gap-1 text-sm text-ink-2">
            {routePattern === "lawnmower" && (
              <>
                <div className="flex justify-between">
                  <dt>격자 간격</dt>
                  <dd className="num">{LEVEL_PRESETS[draft.level].spacingM}m</dd>
                </div>
                <div className="flex justify-between">
                  <dt>촬영 간격</dt>
                  <dd className="num">{LEVEL_PRESETS[draft.level].captureIntervalM}m</dd>
                </div>
              </>
            )}
            <div className="flex justify-between">
              <dt>비행 속도</dt>
              <dd className="num">{LEVEL_PRESETS[draft.level].autoFlightSpeedMs}m/s</dd>
            </div>
          </dl>
        )}

        <details className="rounded-lg border border-line p-3 text-sm">
          <summary className="tap-target cursor-pointer font-semibold break-keep text-ink-1">
            고급 설정
          </summary>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="break-keep text-[12.5px] font-semibold text-ink-1">비행 고도(m)</span>
              <input
                type="number"
                max={MAX_FLIGHT_ALTITUDE_M}
                value={draft.altitudeM}
                onChange={(e) => updateNumber("altitudeM", e.target.value)}
                aria-invalid={draft.altitudeM > MAX_FLIGHT_ALTITUDE_M}
                className="input num"
              />
              {draft.altitudeM > MAX_FLIGHT_ALTITUDE_M && (
                <span className="text-[12.5px] font-semibold break-keep text-crit-ink">
                  {MAX_FLIGHT_ALTITUDE_M}m 이하여야 합니다(법정 비행제한 고도{" "}
                  {MAX_ALTITUDE_M}m).
                </span>
              )}
            </label>
            <label className="flex flex-col gap-1">
              <span className="break-keep text-[12.5px] font-semibold text-ink-1">
                이륙 안전 고도(m)
              </span>
              <input
                type="number"
                value={draft.takeoffSecurityHeightM}
                onChange={(e) => updateNumber("takeoffSecurityHeightM", e.target.value)}
                className="input num"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="break-keep text-[12.5px] font-semibold text-ink-1">
                전이 구간 속도(m/s)
              </span>
              <input
                type="number"
                value={draft.globalTransitionalSpeedMs}
                onChange={(e) => updateNumber("globalTransitionalSpeedMs", e.target.value)}
                className="input num"
              />
            </label>

            <p className="text-xs break-keep text-ink-muted sm:col-span-2">
              드론/페이로드 값 — 실기 검증 전 원시값입니다.
            </p>
            <div className="grid grid-cols-3 gap-2 sm:col-span-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs break-keep text-ink-1">드론 enum</span>
                <input
                  type="number"
                  value={draft.droneEnumValue}
                  onChange={(e) => updateNumber("droneEnumValue", e.target.value)}
                  className="input num"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs break-keep text-ink-1">서브 enum</span>
                <input
                  type="number"
                  value={draft.droneSubEnumValue}
                  onChange={(e) => updateNumber("droneSubEnumValue", e.target.value)}
                  className="input num"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs break-keep text-ink-1">페이로드 enum</span>
                <input
                  type="number"
                  value={draft.payloadEnumValue}
                  onChange={(e) => updateNumber("payloadEnumValue", e.target.value)}
                  className="input num"
                />
              </label>
            </div>

            <label className="flex flex-col gap-1">
              <span className="break-keep text-[12.5px] font-semibold text-ink-1">
                시점 정책 ID (viewpointPolicyId)
              </span>
              <input
                value={draft.viewpointPolicyId}
                onChange={(e) => update({ viewpointPolicyId: e.target.value })}
                className="input"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="break-keep text-[12.5px] font-semibold text-ink-1">
                위험 정책팩 ID (riskPolicyPackId)
              </span>
              <input
                value={draft.riskPolicyPackId}
                onChange={(e) => update({ riskPolicyPackId: e.target.value })}
                className="input"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="break-keep text-[12.5px] font-semibold text-ink-1">
                대체 정책 ID (fallbackPolicyId)
              </span>
              <input
                value={draft.fallbackPolicyId}
                onChange={(e) => update({ fallbackPolicyId: e.target.value })}
                className="input"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="break-keep text-[12.5px] font-semibold text-ink-1">
                촬영 정책 ID (capturePolicyId)
              </span>
              <input
                value={draft.capturePolicyId}
                onChange={(e) => update({ capturePolicyId: e.target.value })}
                className="input"
              />
            </label>
          </div>
        </details>
      </div>
    );
  } else if (draft.step === REVIEW_STEP) {
    const targetOpt = TARGET_OPTIONS.find((o) => o.value === draft.target);
    stepContent = (
      <dl className="flex flex-col gap-3 text-sm sm:col-span-2">
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">대상</dt>
          <dd className="text-right break-keep">{targetOpt?.label ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">목적</dt>
          <dd className="text-right break-keep">
            {selectedPurpose?.label ?? "—"} ({draft.missionType ?? "—"})
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">조사 수준</dt>
          <dd className="text-right">{draft.level ? LEVEL_PRESETS[draft.level].label : "—"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">AOI 꼭짓점</dt>
          <dd className="num text-right">{draft.aoi.length}개</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">비행 고도</dt>
          <dd className="num text-right">{draft.altitudeM}m</dd>
        </div>
        {routePattern === "lawnmower" && draft.level && (
          <>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-2">격자 간격</dt>
              <dd className="num text-right">{LEVEL_PRESETS[draft.level].spacingM}m</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-2">촬영 간격</dt>
              <dd className="num text-right">
                {LEVEL_PRESETS[draft.level].captureIntervalM}m
              </dd>
            </div>
          </>
        )}
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">비행 속도</dt>
          <dd className="num text-right">
            {draft.level ? LEVEL_PRESETS[draft.level].autoFlightSpeedMs : "—"}m/s
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">이륙 안전 고도</dt>
          <dd className="num text-right">{draft.takeoffSecurityHeightM}m</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">전이 구간 속도</dt>
          <dd className="num text-right">{draft.globalTransitionalSpeedMs}m/s</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-ink-2">드론/서브/페이로드 enum</dt>
          <dd className="num text-right">
            {draft.droneEnumValue}/{draft.droneSubEnumValue}/{draft.payloadEnumValue}
          </dd>
        </div>
        <div className="flex flex-col gap-1">
          <dt className="text-ink-2">정책 ID</dt>
          <dd className="num text-xs break-token text-ink-2">
            시점 {draft.viewpointPolicyId} · 위험 {draft.riskPolicyPackId} · 대체{" "}
            {draft.fallbackPolicyId} · 촬영 {draft.capturePolicyId}
          </dd>
        </div>
      </dl>
    );
  } else if (draft.step === SUBMIT_STEP) {
    stepContent = (
      <div className="flex flex-col gap-4 sm:col-span-2">
        {status === "pending" && (
          <p className="text-sm break-keep text-ink-2">
            계획을 계산하고 계약을 발급하는 중입니다…
          </p>
        )}
        {status === "success" && result && (
          <div className="flex flex-col gap-3 rounded-lg border border-safe/30 bg-safe-bg p-4 text-sm">
            <p className="font-medium break-keep text-safe-ink">
              임무 계약이 발급되었습니다.
            </p>
            <dl className="flex flex-col gap-1 text-safe-ink/90">
              <div className="flex justify-between">
                <dt>웨이포인트 수</dt>
                <dd className="num">{result.waypointCount}</dd>
              </div>
              <div className="flex justify-between">
                <dt>커버리지</dt>
                <dd className="num">{formatCoverageRatio(result.coverageRatio)}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt>KMZ SHA-256</dt>
                <dd className="num text-right text-xs break-token">{result.kmzSha256}</dd>
              </div>
            </dl>
          </div>
        )}
        {status === "error" && (
          <p className="text-sm break-keep text-ink-2">
            아래 오류를 확인한 뒤 다시 시도하거나 이전 단계로 돌아가 입력을 수정하세요.
          </p>
        )}
      </div>
    );
  }

  return (
    <WizardShell
      title={`${site.status === "UNMAPPED" ? "베이스라인 임무 발급" : "새 현장조사"} — ${site.name}`}
      stepLabels={STEP_LABELS}
      currentStep={draft.step}
      onBack={onBack}
      onNext={onNext}
      nextLabel={nextLabel}
      nextDisabled={nextDisabled}
      nextPending={nextPending}
      exitHref={`/sites/${encodeURIComponent(site.siteId)}`}
      error={
        draft.step === SUBMIT_STEP && status === "error" ? (
          <ErrorState message={errorMessage ?? "요청을 처리하지 못했습니다."} />
        ) : undefined
      }
    >
      {stepContent}
    </WizardShell>
  );
}
