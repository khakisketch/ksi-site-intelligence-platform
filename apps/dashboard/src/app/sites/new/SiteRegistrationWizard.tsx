"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { WizardShell } from "@/components/wizard/WizardShell";
import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { ErrorState } from "@/components/ui/ErrorState";
import { useDraftState } from "@/hooks/useDraftState";
import { isConvexPolygon } from "@/lib/geometry";
import type { AoiVertex, MissionPlanRequest, MissionPlanResponse, SiteFrame } from "@/lib/core-api/types";

const STEP_LABELS = [
  "기본정보",
  "외곽 선택",
  "좌표계·기준고도",
  "BIM·도면 가져오기",
  "비행 금지·민감 구역",
  "Baseline Mapping 계획",
  "처리·검증",
  "완료",
];

interface WizardFormState {
  siteId: string;
  name: string;
  aoi: AoiVertex[];
  crs: string;
  verticalDatum: string;
  transformVersion: string;
  altitudeM: number;
  excludedVolumes: string[];
  spacingM: number;
  captureIntervalM: number;
  autoFlightSpeedMs: number;
  takeoffSecurityHeightM: number;
  globalTransitionalSpeedMs: number;
  droneEnumValue: number;
  droneSubEnumValue: number;
  payloadEnumValue: number;
  viewpointPolicyId: string;
  riskPolicyPackId: string;
  fallbackPolicyId: string;
  capturePolicyId: string;
  objectives: string[];
}

// 서버가 고정한 규제 고도 상한(항공안전법 일반 비행제한 고도). 계약의
// maxAltitudeM 이 이 값을 넘으면 서버가 422 로 거부하므로, 여기서 먼저 막아
// 사용자가 8단계를 다 채우고 나서야 실패를 보는 일을 없앤다.
const MAX_ALTITUDE_M = 150;
// 계약 봉투는 비행 고도보다 10m 여유를 둔다 — 그 여유까지 상한 안이어야 한다.
const MAX_FLIGHT_ALTITUDE_M = MAX_ALTITUDE_M - 10;

const INITIAL_FORM: WizardFormState = {
  siteId: "",
  name: "",
  aoi: [],
  crs: "",
  verticalDatum: "",
  transformVersion: "1.0.0",
  altitudeM: 40,
  excludedVolumes: [],
  spacingM: 20,
  captureIntervalM: 15,
  autoFlightSpeedMs: 5,
  takeoffSecurityHeightM: 20,
  globalTransitionalSpeedMs: 10,
  droneEnumValue: 99,
  droneSubEnumValue: 0,
  payloadEnumValue: 65534,
  viewpointPolicyId: "default-viewpoint-policy",
  riskPolicyPackId: "default-risk-policy",
  fallbackPolicyId: "default-fallback-policy",
  capturePolicyId: "default-capture-policy",
  objectives: ["초기 매핑"],
};

const SITE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

const inputClassName = "input";
const numericInputClassName = "input num";

type SubmitPhase = "idle" | "pending" | "error" | "success";

interface SubmitResult {
  waypointCount: number;
  coverageRatio: number | null;
  kmzSha256: string;
}

async function parseJsonSafe(res: Response): Promise<{ message?: string; code?: string }> {
  try {
    return (await res.json()) as { message?: string; code?: string };
  } catch {
    return {};
  }
}

function formatCoverage(ratio: number | null): string {
  if (ratio === null) return "정보 없음";
  return `${(ratio * 100).toFixed(1)}%`;
}

function Field({
  label,
  helpText,
  error,
  required,
  wide,
  children,
}: {
  label: string;
  helpText?: string;
  /** 값이 있는데 조건을 어겼을 때만 넘긴다 — 빈 필수 필드는 `required` 로 충분하다. */
  error?: string;
  required?: boolean;
  /** 2열 그리드에서 전체 폭을 써야 하는 필드(예: 이름·좁은 폭에서 읽기 나쁜 필드). */
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    // label 이 입력을 감싼다 — 형제로 두면 접근가능 이름이 placeholder 로 잡히고,
    // placeholder 는 입력을 시작하면 사라진다(SiteRegistrationOnlyWizard.tsx 의 같은
    // 주석 참조 — 2026-08-04 렌더 확인에서 실제 재현).
    <div className={`flex flex-col gap-1.5 ${wide ? "sm:col-span-2" : ""}`}>
      <label className="flex flex-col gap-1.5">
        <span className="text-[12.5px] font-semibold break-keep text-ink-1">
          {label}
          {required && (
            <span aria-hidden className="ml-0.5 text-crit">
              *
            </span>
          )}
        </span>
        {children}
      </label>
      {error ? (
        <p className="text-[11.5px] font-semibold break-keep text-crit-ink">{error}</p>
      ) : (
        helpText && <p className="text-[11.5px] break-keep text-ink-muted">{helpText}</p>
      )}
    </div>
  );
}

function TagInput({
  label,
  helpText,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  helpText?: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  function commit() {
    const parts = draft
      .split(",")
      .map((part) => part.trim())
      .filter((part) => part.length > 0);
    if (parts.length === 0) return;
    onChange([...values, ...parts]);
    setDraft("");
  }

  return (
    <div className="flex flex-col gap-2 sm:col-span-2">
      <label className="text-[12.5px] font-semibold break-keep text-ink-1">{label}</label>
      {helpText && <p className="text-[11.5px] break-keep text-ink-muted">{helpText}</p>}
      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
          }}
          placeholder={placeholder}
          className={inputClassName}
        />
        <button type="button" onClick={commit} className="btn shrink-0">
          추가
        </button>
      </div>
      {values.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {values.map((value, index) => (
            <li
              key={`${value}-${index}`}
              className="flex min-h-9 items-center gap-1 rounded-full bg-sunk py-1 pr-1 pl-3 text-[13px] break-keep text-ink-1"
            >
              {value}
              {/* 삭제 버튼은 실제로 누르는 것이므로 .tap-target 을 탄다 —
                  고정 24px 로 두면 이 제품의 1급 기기(터치 태블릿)에서만 못 누른다.
                  같은 컴포넌트의 '추가' 버튼은 이미 .btn 을 쓴다(비대칭이었다). */}
              <button
                type="button"
                aria-label={`${value} 삭제`}
                onClick={() => onChange(values.filter((_, i) => i !== index))}
                className="tap-target flex min-w-9 items-center justify-center rounded-full px-2 text-ink-2 hover:bg-line hover:text-ink-1"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SiteRegistrationWizard() {
  const router = useRouter();
  const [form, setForm, clearDraft] = useDraftState<WizardFormState>(
    "ksi-wizard-site-registration",
    INITIAL_FORM,
  );
  const [currentStep, setCurrentStep] = useState(0);
  const [submitPhase, setSubmitPhase] = useState<SubmitPhase>("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<SubmitResult | null>(null);

  const siteRegisteredRef = useRef(false);
  // siteRegisteredRef 와 다르다 — 이쪽은 "성공했다"가 아니라 "보냈다"를 기억한다.
  const sitePostAttemptedRef = useRef(false);
  const missionIdRef = useRef<string | null>(null);
  const draftClearedRef = useRef(false);

  function update(partial: Partial<WizardFormState>) {
    setForm({ ...form, ...partial });
  }

  async function runSubmission() {
    setSubmitPhase("pending");
    setSubmitError(null);

    const siteId = form.siteId.trim();
    const siteFrame: SiteFrame = {
      crs: form.crs.trim(),
      verticalDatum: form.verticalDatum.trim(),
      unit: "meter",
      transformVersion: form.transformVersion.trim(),
    };

    try {
      if (!siteRegisteredRef.current) {
        // POST 를 보내기 전에 표시한다(응답을 못 받아도 서버는 등록했을 수 있다).
        const wasAttemptedBefore = sitePostAttemptedRef.current;
        sitePostAttemptedRef.current = true;
        const siteRes = await fetch("/api/sites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ siteId, name: form.name.trim(), siteFrame }),
        });
        if (!siteRes.ok) {
          const body = await parseJsonSafe(siteRes);
          // 409 는 **재시도일 때만** 성공이다 — 첫 시도의 409 는 남이 이미 쓴 siteId 다
          // (SiteRegistrationOnlyWizard 의 같은 주석 참조, 독립 재검토 2026-08-04).
          // **이전 값**을 본다(위에서 true 로 세웠으므로 현재 값은 항상 참이다).
          const alreadyRegistered =
            wasAttemptedBefore && siteRes.status === 409 && body.code === "DUPLICATE_SITE_ID";
          if (!alreadyRegistered) {
            setSubmitError(body.message ?? "요청을 처리하지 못했습니다.");
            setSubmitPhase("error");
            return;
          }
        }
        siteRegisteredRef.current = true;
      }

      if (!missionIdRef.current) {
        missionIdRef.current = `${siteId}-baseline-${Date.now()}`;
      }

      const planRequest: MissionPlanRequest = {
        contract: {
          missionId: missionIdRef.current,
          siteId,
          missionType: "BASELINE_MAPPING",
          siteFrame,
          flightEnvelope: {
            // allowedVolumes 는 실제 지오메트리가 아니라 라벨이지만(§7 구현 노트와 동일한
            // opaque-label 취급), 빈 배열은 "허용 구역 없음"으로 해석돼 422
            // EMPTY_ALLOWED_VOLUMES 로 거부된다(packages/mission-planning coverage.py) —
            // AOI 전체를 커버하는 단일 허용 구역 라벨을 기본값으로 선언한다.
            allowedVolumes: ["site-boundary"],
            excludedVolumes: form.excludedVolumes,
            minAltitudeM: 0,
            maxAltitudeM: Math.max(form.altitudeM + 10, 30),
          },
          objectives: form.objectives,
          viewpointPolicyId: form.viewpointPolicyId.trim(),
          riskPolicyPackId: form.riskPolicyPackId.trim(),
          fallbackPolicyId: form.fallbackPolicyId.trim(),
          capturePolicyId: form.capturePolicyId.trim(),
        },
        aoi: { vertices: form.aoi },
        route: {
          altitudeM: form.altitudeM,
          spacingM: form.spacingM,
          captureIntervalM: form.captureIntervalM,
        },
        drone: {
          droneEnumValue: form.droneEnumValue,
          droneSubEnumValue: form.droneSubEnumValue,
          payloadEnumValue: form.payloadEnumValue,
        },
        wayline: {
          autoFlightSpeedMs: form.autoFlightSpeedMs,
          takeoffSecurityHeightM: form.takeoffSecurityHeightM,
          globalTransitionalSpeedMs: form.globalTransitionalSpeedMs,
        },
      };

      const planRes = await fetch("/api/mission-plans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(planRequest),
      });
      if (!planRes.ok) {
        const body = await parseJsonSafe(planRes);
        setSubmitError(body.message ?? "요청을 처리하지 못했습니다.");
        setSubmitPhase("error");
        return;
      }
      const plan = (await planRes.json()) as MissionPlanResponse;
      setResult({
        waypointCount: plan.waypointCount,
        coverageRatio: plan.coverageRatio,
        kmzSha256: plan.kmzSha256,
      });
      setSubmitPhase("success");
      setCurrentStep(7);
      // 셸(사이드바 현장·임무 배지)은 layout 에 있어 클라이언트 네비게이션으로는 다시
      // 그려지지 않는다 — 방금 만든 현장·임무가 반영되도록 서버 렌더를 한 번 요청한다.
      router.refresh();
    } catch {
      setSubmitError("요청을 처리하지 못했습니다.");
      setSubmitPhase("error");
    }
  }

  // 7단계(처리·검증) 진입 시 자동으로 API 호출을 시작한다(spec §7 "이 스텝 진입 시").
  useEffect(() => {
    if (currentStep === 6 && submitPhase === "idle") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 외부 API 호출(fetch) 트리거, 순수 파생 state 아님
      void runSubmission();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 최신 form 은 클로저로 캡처, currentStep 전이에만 반응
  }, [currentStep]);

  // 8단계(완료 요약) 진입 시 draft 를 정리한다(재작업 방지 목적 달성 후 정리, spec §8).
  useEffect(() => {
    if (currentStep === 7 && !draftClearedRef.current) {
      draftClearedRef.current = true;
      clearDraft();
    }
  }, [currentStep, clearDraft]);

  const trimmedSiteId = form.siteId.trim();
  const stepValid: Record<number, boolean> = {
    0: trimmedSiteId.length > 0 && SITE_ID_PATTERN.test(trimmedSiteId) && form.name.trim().length > 0,
    1: form.aoi.length >= 3 && isConvexPolygon(form.aoi),
    2:
      form.crs.trim().length > 0 &&
      form.verticalDatum.trim().length > 0 &&
      form.transformVersion.trim().length > 0 &&
      form.altitudeM > 0 &&
      form.altitudeM <= MAX_FLIGHT_ALTITUDE_M,
    3: true,
    // 경로 생성 엔진이 회피 비행을 보증하지 못해 excludedVolumes 가 하나라도 있으면
    // 서버가 발급 자체를 거부한다(packages/mission-planning coverage.py) — 이미 등록된
    // 현장이 발급 실패로 남는 함정을 막기 위해 비워야만 다음으로 넘어가게 한다.
    4: form.excludedVolumes.length === 0,
    5:
      form.spacingM > 0 &&
      form.captureIntervalM > 0 &&
      form.autoFlightSpeedMs > 0 &&
      form.takeoffSecurityHeightM >= 1.2 &&
      form.takeoffSecurityHeightM <= 1500 &&
      form.globalTransitionalSpeedMs > 0 &&
      form.globalTransitionalSpeedMs <= 15 &&
      form.objectives.length > 0 &&
      form.viewpointPolicyId.trim().length > 0 &&
      form.riskPolicyPackId.trim().length > 0 &&
      form.fallbackPolicyId.trim().length > 0 &&
      form.capturePolicyId.trim().length > 0,
    6: submitPhase !== "pending",
    7: true,
  };

  function handleBack() {
    setCurrentStep((step) => {
      if (step === 6) {
        // 6단계로 재진입할 때 최신 입력값으로 다시 시도하도록 리셋한다.
        siteRegisteredRef.current = false;
        missionIdRef.current = null;
        setSubmitPhase("idle");
        setSubmitError(null);
      }
      return step - 1;
    });
  }

  function handleNext() {
    if (currentStep === 7) {
      router.push(`/sites/${encodeURIComponent(form.siteId.trim())}`);
      return;
    }
    if (currentStep === 6) {
      void runSubmission();
      return;
    }
    setCurrentStep((step) => step + 1);
  }

  const canGoBack = currentStep > 0 && currentStep !== 7 && !(currentStep === 6 && submitPhase === "pending");

  let nextLabel = "다음";
  if (currentStep === 6) {
    nextLabel = submitPhase === "error" ? "다시 시도" : "다음";
  } else if (currentStep === 7) {
    nextLabel = "현장 상세로 이동";
  }

  // 값이 있는데 조건을 어긴 경우에만 에러를 보여준다(빈 필수 필드는 다음 버튼
  // disable + label 의 붉은 * 로 충분하다 — 타이핑 중마다 에러가 뜨면 소음이 된다).
  const siteIdError =
    trimmedSiteId.length > 0 && !SITE_ID_PATTERN.test(trimmedSiteId)
      ? "영숫자로 시작하고 이후 영숫자·-·_·. 만 쓸 수 있습니다(공백·/ 금지)."
      : undefined;
  const altitudeError = !(form.altitudeM > 0)
    ? "0보다 큰 값을 입력하세요."
    : form.altitudeM > MAX_FLIGHT_ALTITUDE_M
      ? `${MAX_FLIGHT_ALTITUDE_M}m 이하여야 합니다(법정 비행제한 고도 ${MAX_ALTITUDE_M}m).`
      : undefined;
  const spacingError = !(form.spacingM > 0) ? "0보다 큰 값을 입력하세요." : undefined;
  const captureIntervalError = !(form.captureIntervalM > 0)
    ? "0보다 큰 값을 입력하세요."
    : undefined;
  const autoFlightSpeedError =
    !(form.autoFlightSpeedMs > 0) ? "0보다 큰 값을 입력하세요." : undefined;
  const takeoffHeightError =
    form.takeoffSecurityHeightM >= 1.2 && form.takeoffSecurityHeightM <= 1500
      ? undefined
      : "1.2~1500 사이 값이어야 합니다.";
  const transitionalSpeedError =
    form.globalTransitionalSpeedMs > 0 && form.globalTransitionalSpeedMs <= 15
      ? undefined
      : "0보다 크고 15 이하여야 합니다.";

  return (
    <WizardShell
      title="현장 등록"
      stepLabels={STEP_LABELS}
      currentStep={currentStep}
      onBack={canGoBack ? handleBack : undefined}
      onNext={handleNext}
      nextLabel={nextLabel}
      nextDisabled={!stepValid[currentStep]}
      nextPending={currentStep === 6 && submitPhase === "pending"}
      error={
        currentStep === 6 && submitError ? <ErrorState message={submitError} /> : undefined
      }
      exitHref="/sites"
    >
      {currentStep === 0 && (
        <>
          <Field
            label="현장 ID"
            helpText="영숫자로 시작, -/_/. 만 허용, 공백·/ 금지"
            error={siteIdError}
            required
          >
            <input
              type="text"
              value={form.siteId}
              onChange={(event) => update({ siteId: event.target.value })}
              placeholder="SITE-2026-001"
              aria-invalid={Boolean(siteIdError)}
              className={inputClassName}
            />
          </Field>
          <Field label="현장 이름" required>
            <input
              type="text"
              value={form.name}
              onChange={(event) => update({ name: event.target.value })}
              placeholder="예: OO산업단지 3공구 신축공사 현장"
              className={inputClassName}
            />
          </Field>
        </>
      )}

      {currentStep === 1 && (
        <div className="flex flex-col gap-3 sm:col-span-2">
          <p className="text-sm break-keep text-ink-2">
            지도에서 폴리곤을 그려 현장 외곽을 표시하세요. 최소 3개 꼭짓점이 필요하며, 이
            Wizard는 매핑(격자) 경로만 발급하므로 오목한(L자 등) 외곽은 지원하지 않습니다.
          </p>
          <AoiPolygonMap value={form.aoi} onChange={(aoi) => update({ aoi })} />
          {form.aoi.length >= 3 && !isConvexPolygon(form.aoi) && (
            <p className="text-sm break-keep text-high-ink">
              그려진 외곽이 볼록하지 않습니다. 매핑 경로는 볼록 다각형에서만 발급됩니다 — 다시
              그리세요.
            </p>
          )}
        </div>
      )}

      {currentStep === 2 && (
        <>
          <Field label="좌표계(CRS)" helpText="예: EPSG:5186" required>
            <input
              type="text"
              value={form.crs}
              onChange={(event) => update({ crs: event.target.value })}
              placeholder="EPSG:5186"
              className={inputClassName}
            />
          </Field>
          <Field label="수직 기준(Vertical Datum)" helpText="예: KNGeoid2018" required>
            <input
              type="text"
              value={form.verticalDatum}
              onChange={(event) => update({ verticalDatum: event.target.value })}
              placeholder="KNGeoid2018"
              className={inputClassName}
            />
          </Field>
          <Field label="단위" helpText="이 버전은 미터 고정입니다">
            <input type="text" value="meter" disabled className={inputClassName} />
          </Field>
          <Field label="좌표 변환 버전(transformVersion)">
            <input
              type="text"
              value={form.transformVersion}
              onChange={(event) => update({ transformVersion: event.target.value })}
              className={inputClassName}
            />
          </Field>
          <Field
            label="매핑 비행 고도 (m)"
            helpText="이후 단계(경로 계획)에서도 사용됩니다"
            error={altitudeError}
          >
            <input
              type="number"
              value={form.altitudeM}
              onChange={(event) => update({ altitudeM: event.target.valueAsNumber })}
              aria-invalid={Boolean(altitudeError)}
              className={numericInputClassName}
            />
          </Field>
        </>
      )}

      {currentStep === 3 && (
        <p className="text-sm break-keep text-ink-2 sm:col-span-2">
          BIM/도면·기존 모델 가져오기는 이 버전에서는 지원하지 않습니다. &quot;다음&quot;을 눌러
          계속 진행하세요.
        </p>
      )}

      {currentStep === 4 && (
        <>
          <TagInput
            label="비행 금지·민감 구역"
            helpText="이 버전은 회피 경로 생성을 지원하지 않습니다 — 값을 입력하면 다음으로 진행할 수 없습니다. 실제 회피가 필요하면 등록 후 별도로 처리하세요."
            values={form.excludedVolumes}
            onChange={(excludedVolumes) => update({ excludedVolumes })}
            placeholder="구역 이름을 입력 후 Enter (쉼표로 여러 개 추가 가능)"
          />
          {form.excludedVolumes.length > 0 && (
            <p className="text-sm break-keep text-high-ink sm:col-span-2">
              현재 경로 생성 엔진이 구역 회피를 보증할 수 없어, 값이 있으면 7단계에서 발급이
              거부됩니다. 비워두고 계속하세요.
            </p>
          )}
        </>
      )}

      {currentStep === 5 && (
        <>
          <Field
            label="웨이포인트 간격 spacingM (m)"
            helpText="lawnmower 패턴의 필수값입니다"
            error={spacingError}
          >
            <input
              type="number"
              value={form.spacingM}
              onChange={(event) => update({ spacingM: event.target.valueAsNumber })}
              aria-invalid={Boolean(spacingError)}
              className={numericInputClassName}
            />
          </Field>
          <Field
            label="촬영 간격 captureIntervalM (m)"
            helpText="스캔선을 따라 이 간격마다 촬영합니다. 값이 클수록 사진이 적고 겹침이 줄어듭니다"
            error={captureIntervalError}
          >
            <input
              type="number"
              value={form.captureIntervalM}
              onChange={(event) => update({ captureIntervalM: event.target.valueAsNumber })}
              aria-invalid={Boolean(captureIntervalError)}
              className={numericInputClassName}
            />
          </Field>
          <Field label="자동 비행 속도 (m/s)" error={autoFlightSpeedError}>
            <input
              type="number"
              value={form.autoFlightSpeedMs}
              onChange={(event) => update({ autoFlightSpeedMs: event.target.valueAsNumber })}
              aria-invalid={Boolean(autoFlightSpeedError)}
              className={numericInputClassName}
            />
          </Field>
          <Field label="이륙 안전고도 (m)" helpText="최소 1.2, 최대 1500" error={takeoffHeightError}>
            <input
              type="number"
              value={form.takeoffSecurityHeightM}
              onChange={(event) => update({ takeoffSecurityHeightM: event.target.valueAsNumber })}
              aria-invalid={Boolean(takeoffHeightError)}
              className={numericInputClassName}
            />
          </Field>
          <Field label="전환 비행 속도 (m/s)" helpText="최대 15" error={transitionalSpeedError}>
            <input
              type="number"
              value={form.globalTransitionalSpeedMs}
              onChange={(event) => update({ globalTransitionalSpeedMs: event.target.valueAsNumber })}
              aria-invalid={Boolean(transitionalSpeedError)}
              className={numericInputClassName}
            />
          </Field>

          <details className="rounded-lg border border-line px-4 py-3 sm:col-span-2">
            <summary className="tap-target cursor-pointer text-sm font-semibold break-keep text-ink-1">
              고급 설정
            </summary>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field
                label="droneEnumValue"
                helpText="DJI WPML 사양 원시값 — 실기 검증 전이라 자동 결정하지 않습니다"
              >
                <input
                  type="number"
                  value={form.droneEnumValue}
                  onChange={(event) => update({ droneEnumValue: event.target.valueAsNumber })}
                  className={numericInputClassName}
                />
              </Field>
              <Field
                label="droneSubEnumValue"
                helpText="DJI WPML 사양 원시값 — 실기 검증 전이라 자동 결정하지 않습니다"
              >
                <input
                  type="number"
                  value={form.droneSubEnumValue}
                  onChange={(event) => update({ droneSubEnumValue: event.target.valueAsNumber })}
                  className={numericInputClassName}
                />
              </Field>
              <Field
                label="payloadEnumValue"
                helpText="DJI WPML 사양 원시값 — 실기 검증 전이라 자동 결정하지 않습니다"
              >
                <input
                  type="number"
                  value={form.payloadEnumValue}
                  onChange={(event) => update({ payloadEnumValue: event.target.valueAsNumber })}
                  className={numericInputClassName}
                />
              </Field>
              <Field
                label="viewpointPolicyId"
                helpText="정책 팩 참조 ID — 현재 레지스트리가 없어 직접 입력합니다"
              >
                <input
                  type="text"
                  value={form.viewpointPolicyId}
                  onChange={(event) => update({ viewpointPolicyId: event.target.value })}
                  className={inputClassName}
                />
              </Field>
              <Field
                label="riskPolicyPackId"
                helpText="정책 팩 참조 ID — 현재 레지스트리가 없어 직접 입력합니다"
              >
                <input
                  type="text"
                  value={form.riskPolicyPackId}
                  onChange={(event) => update({ riskPolicyPackId: event.target.value })}
                  className={inputClassName}
                />
              </Field>
              <Field
                label="fallbackPolicyId"
                helpText="정책 팩 참조 ID — 현재 레지스트리가 없어 직접 입력합니다"
              >
                <input
                  type="text"
                  value={form.fallbackPolicyId}
                  onChange={(event) => update({ fallbackPolicyId: event.target.value })}
                  className={inputClassName}
                />
              </Field>
              <Field
                label="capturePolicyId"
                helpText="정책 팩 참조 ID — 현재 레지스트리가 없어 직접 입력합니다"
              >
                <input
                  type="text"
                  value={form.capturePolicyId}
                  onChange={(event) => update({ capturePolicyId: event.target.value })}
                  className={inputClassName}
                />
              </Field>
              <TagInput
                label="objectives(임무 목적)"
                values={form.objectives}
                onChange={(objectives) => update({ objectives })}
                placeholder="목적을 입력 후 Enter"
              />
            </div>
          </details>
        </>
      )}

      {currentStep === 6 && (
        <p className="text-sm break-keep text-ink-2 sm:col-span-2">
          {submitPhase === "pending" && "현장을 등록하고 임무 계획을 생성하는 중입니다…"}
          {submitPhase === "error" && "처리 중 문제가 발생했습니다. 아래에서 원인을 확인하고 다시 시도하세요."}
          {submitPhase === "idle" && "처리를 시작합니다…"}
        </p>
      )}

      {currentStep === 7 && (
        <div className="flex flex-col gap-3 sm:col-span-2">
          {result ? (
            <dl className="flex flex-col gap-3 rounded-lg border border-line bg-page px-4 py-3 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="break-keep text-ink-2">웨이포인트 수</dt>
                <dd className="num font-medium">{result.waypointCount.toLocaleString("ko-KR")}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="break-keep text-ink-2">커버리지</dt>
                <dd className="num font-medium">{formatCoverage(result.coverageRatio)}</dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="break-keep text-ink-2">KMZ SHA-256</dt>
                <dd className="num text-xs break-token">{result.kmzSha256}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm break-keep text-ink-2">발급 결과를 불러오지 못했습니다.</p>
          )}
        </div>
      )}
    </WizardShell>
  );
}
