"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { WizardShell } from "@/components/wizard/WizardShell";
import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { ErrorState } from "@/components/ui/ErrorState";
import { useDraftState } from "@/hooks/useDraftState";
import { buildDataResidencyInput, type EgressChoice } from "@/lib/data-residency";
import { isConvexPolygon } from "@/lib/geometry";
import type { SiteRegistrationMode } from "@/lib/core-api/permissions";
import {
  EGRESS_CHOICE_OPTIONS,
  Field,
  SITE_ID_PATTERN,
  isRetryOfOwnSitePost,
  nextOwnPostSiteId,
  parseJsonSafe,
} from "@/lib/site-registration/shared";
import type { AoiVertex, SiteFrame } from "@/lib/core-api/types";

// 현장 등록은 기본정보 → AOI/좌표계 → 확인의 3단계로 끝낸다. 베이스라인 조사는
// 등록 성공 뒤 현장 작업공간에서 별도로 시작한다. 현장 등록과 Mission 발급을 한
// Wizard에 묶지 않는 것은 ADR-KSI-026의 작업 경계다.
const STEP_LABELS = ["기본정보", "현장 범위·좌표계", "확인·등록"];
const DRAFT_STORAGE_KEY = "ksi-wizard-site-registration-only";
const CANONICAL_UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

interface FormState {
  siteId: string;
  bootstrapRequestId?: string;
  name: string;
  aoi: AoiVertex[];
  crs: string;
  verticalDatum: string;
  transformVersion: string;
  /** 데이터 반출 선언(INV-050) — "unset" 은 미응답, 등록 후 다시 물을 경로가 없다. */
  egressChoice: EgressChoice;
  jurisdiction: string;
  aiEgressAllowed: boolean;
}

const INITIAL_FORM: FormState = {
  siteId: "",
  name: "",
  aoi: [],
  crs: "",
  verticalDatum: "",
  transformVersion: "1.0.0",
  egressChoice: "unset",
  jurisdiction: "",
  aiEgressAllowed: false,
};

/**
 * A generated identifier is a starting point, not a server-side identity.
 * It is saved with the browser draft and may always be edited before posting.
 */
export function createGeneratedSiteId(now = Date.now()): string {
  const randomSegment = globalThis.crypto.randomUUID().replaceAll("-", "").slice(0, 8);
  return `site-${now.toString(36)}-${randomSegment}`;
}

function migrateRegistrationDraft(stored: unknown): FormState {
  if (!stored || typeof stored !== "object" || Array.isArray(stored)) return INITIAL_FORM;
  const candidate = stored as Partial<FormState>;
  return {
    ...INITIAL_FORM,
    ...candidate,
    bootstrapRequestId:
      typeof candidate.bootstrapRequestId === "string" &&
      CANONICAL_UUID_PATTERN.test(candidate.bootstrapRequestId)
        ? candidate.bootstrapRequestId
        : undefined,
    aoi: Array.isArray(candidate.aoi) ? candidate.aoi : INITIAL_FORM.aoi,
    aiEgressAllowed:
      typeof candidate.aiEgressAllowed === "boolean"
        ? candidate.aiEgressAllowed
        : INITIAL_FORM.aiEgressAllowed,
  };
}

const inputClassName = "input";

type SubmitPhase = "idle" | "pending" | "error" | "success";

export function SiteRegistrationOnlyWizard({
  mode,
}: {
  mode: Exclude<SiteRegistrationMode, "DENIED">;
}) {
  const router = useRouter();
  const [form, setForm, clearDraft] = useDraftState<FormState>(
    DRAFT_STORAGE_KEY,
    INITIAL_FORM,
    migrateRegistrationDraft,
  );
  const [currentStep, setCurrentStep] = useState(0);
  const [draftReady, setDraftReady] = useState(false);
  const initialSiteIdResolvedRef = useRef(false);
  // "이 실행에서 어떤 siteId 로 이미 POST 를 보냈나" — 409 를 재시도로 해석해도
  // 되는지의 유일한 근거. **siteId 로 스코프한다** — 그냥 boolean 이면 siteId 'A'
  // 로 실패한 뒤 사용자가 무관한 siteId 'B' 로 고쳐 재제출했을 때도 'B' 의 409 를
  // "내 재시도"로 오판한다(isRetryOfOwnSitePost 주석 참조).
  const postAttemptedSiteIdRef = useRef<string | null>(null);
  const [submitPhase, setSubmitPhase] = useState<SubmitPhase>("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [registeredSiteId, setRegisteredSiteId] = useState<string | null>(null);

  useEffect(() => {
    // useDraftState restores session storage in its own effect. Waiting one
    // task turn keeps a restored custom ID intact before we fill an empty legacy
    // draft, and the ref prevents re-generating after a person clears/edits it.
    const timer = window.setTimeout(() => setDraftReady(true), 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (mode !== "LEGACY_SITE_ID" || !draftReady || initialSiteIdResolvedRef.current) return;
    initialSiteIdResolvedRef.current = true;
    if (form.siteId.trim()) return;
    setForm({ ...form, siteId: createGeneratedSiteId() });
  }, [draftReady, form, mode, setForm]);

  function update(partial: Partial<FormState>) {
    const payloadFields: (keyof FormState)[] = [
      "name",
      "aoi",
      "crs",
      "verticalDatum",
      "transformVersion",
      "egressChoice",
      "jurisdiction",
      "aiEgressAllowed",
    ];
    const payloadChanged = payloadFields.some(
      (field) =>
        Object.prototype.hasOwnProperty.call(partial, field) &&
        !Object.is(partial[field], form[field]),
    );
    const nextForm = { ...form, ...partial };
    if (mode === "MAPPED_BOOTSTRAP" && form.bootstrapRequestId && payloadChanged) {
      nextForm.bootstrapRequestId = undefined;
      setRegisteredSiteId(null);
    }
    setForm(nextForm);
  }

  async function runMappedSubmission() {
    setSubmitPhase("pending");
    setSubmitError(null);

    const bootstrapRequestId = form.bootstrapRequestId ?? globalThis.crypto.randomUUID();
    const pendingForm = { ...form, bootstrapRequestId };
    setForm(pendingForm);

    // The retry key must reach the existing session draft before the POST can
    // have an unknown outcome; the draft hook also keeps it synchronized later.
    try {
      sessionStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(pendingForm));
    } catch {
      setSubmitError("등록 요청 정보를 저장하지 못해 요청을 보내지 않았습니다. 브라우저 저장 공간을 확인한 뒤 다시 시도하세요.");
      setSubmitPhase("error");
      return;
    }

    const siteFrame: SiteFrame = {
      crs: form.crs.trim(),
      verticalDatum: form.verticalDatum.trim(),
      unit: "meter",
      transformVersion: form.transformVersion.trim(),
    };
    const dataResidency = buildDataResidencyInput(form.egressChoice, form.jurisdiction);

    try {
      const res = await fetch("/api/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bootstrapRequestId,
          name: form.name.trim(),
          siteFrame,
          aoi: { vertices: form.aoi },
          dataResidency,
          aiEgressAllowed: form.aiEgressAllowed,
        }),
      });

      if (!res.ok) {
        const body = await parseJsonSafe(res);
        const message =
          res.status === 404
            ? "현장이 현재 부여된 접근 범위 밖에 있을 수 있습니다. KSI에 접근 권한 범위를 다시 발급해 달라고 요청하세요."
            : res.status === 409
              ? body.code === "BOOTSTRAP_REQUEST_CONFLICT"
                ? "같은 등록 요청 키가 다른 내용으로 사용되어 현장을 등록하지 못했습니다. 내용을 확인한 뒤 다시 시도하세요."
                : body.code === "SITE_BOOTSTRAP_LIMIT_REACHED"
                  ? "조직의 현장 등록 한도에 도달해 현장을 등록하지 못했습니다. 관리자에게 문의하세요."
                  : "현장 등록 요청이 충돌했습니다. 내용을 확인한 뒤 다시 시도하세요."
              : body.message ?? "요청을 처리하지 못했습니다.";
        setSubmitError(message);
        setSubmitPhase("error");
        return;
      }

      const body: unknown = await res.json();
      const siteId =
        body && typeof body === "object" && "site" in body &&
        body.site && typeof body.site === "object" && "siteId" in body.site
          ? body.site.siteId
          : undefined;
      if (typeof siteId !== "string" || !siteId.startsWith("site-")) {
        setSubmitError("등록 응답에서 서버가 발급한 현장 ID를 확인하지 못했습니다. 같은 요청으로 다시 시도하세요.");
        setSubmitPhase("error");
        return;
      }

      setRegisteredSiteId(siteId);
      setSubmitPhase("success");
      setCurrentStep(2);
      router.refresh();
    } catch {
      setSubmitError("요청을 처리하지 못했습니다.");
      setSubmitPhase("error");
    }
  }

  async function runSubmission() {
    if (mode === "MAPPED_BOOTSTRAP") {
      await runMappedSubmission();
      return;
    }

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
      // POST 를 **보내기 전에** 표시한다 — 네트워크 예외로 응답을 못 받아도 서버는
      // 등록했을 수 있고, 그 경우 같은 siteId 로 보낸 다음 시도의 409 는 내가 만든 것이다.
      const previousAttemptedSiteId = postAttemptedSiteIdRef.current;
      postAttemptedSiteIdRef.current = siteId;
      const dataResidency = buildDataResidencyInput(form.egressChoice, form.jurisdiction);
      const res = await fetch("/api/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // dataResidency 를 답하지 않았으면(unset) buildDataResidencyInput 이
        // undefined 를 돌려주고, JSON.stringify 가 undefined 값 키를 생략한다 —
        // 그래야 서버가 미선언을 fail-closed(반출 불가)로 해석한다(INV-050).
        body: JSON.stringify({
          siteId,
          name: form.name.trim(),
          siteFrame,
          aoi: { vertices: form.aoi },
          dataResidency,
          aiEgressAllowed: form.aiEgressAllowed,
        }),
      });
      if (!res.ok) {
        const body = await parseJsonSafe(res);
        // 응답을 받았으니 "모른다"를 갱신한다 — 확정 409 면 비운다(아래 주석).
        postAttemptedSiteIdRef.current = nextOwnPostSiteId(siteId, res.status, body.code);
        // 409(DUPLICATE_SITE_ID)를 성공으로 보는 것은 **재시도일 때뿐이다.**
        //
        // 무조건 성공으로 처리하면, 남이 이미 쓴 siteId 를 처음 입력한 사람에게도
        // "현장이 등록되었습니다"라고 말하고 **그 남의 현장**(좌표계가 전혀 다를 수
        // 있다) 상세로 안내한다 — 저장이 일어나지 않았는데 초록불이 뜨는 경로다
        // (독립 재검토 2026-08-04 적발). 첫 시도의 409 는 진짜 중복이므로 실패다.
        // **같은 siteId 로 보냈고 그 결과를 모르는 시도가 있었을 때만** 재시도로
        // 인정한다 — 직전 시도가 409 를 받았다면 서버가 "이미 있다"를 확정한 것이라
        // 그 뒤의 409 도 남의 현장이다(isRetryOfOwnSitePost·nextOwnPostSiteId 주석).
        const isRetryOfOurOwnPost = isRetryOfOwnSitePost(
          previousAttemptedSiteId,
          siteId,
          res.status,
          body.code,
        );
        if (!isRetryOfOurOwnPost) {
          setSubmitError(body.message ?? "요청을 처리하지 못했습니다.");
          setSubmitPhase("error");
          return;
        }
      }
      // 여기 도달하는 경로는 둘이다: 진짜 성공(2xx), 그리고 위에서 **내 재시도로
      // 인정된 409**. 둘 다 "이 현장은 내 것"이므로 판정 근거를 남긴다.
      //
      // 세 번째 인자가 `undefined` 인 것은 실수가 아니라 **의도**다 — 인정된 409
      // 경로에서 실제 코드(DUPLICATE_SITE_ID)를 넘기면 비우기 분기에 걸려 방금
      // 인정한 소유권이 도로 지워진다. 응답이 아니라 "여기 온 이상 내 것"이라는
      // 사실로 갱신하는 자리다. `body` 가 위 블록 스코프라 무심코 넘길 수는 없지만
      // (컴파일 실패), 블록 밖으로 끌어내는 리팩터링이 이 방어를 없앨 수 있다.
      postAttemptedSiteIdRef.current = nextOwnPostSiteId(siteId, res.status, undefined);
      setSubmitPhase("success");
      setCurrentStep(2);
      // 셸(사이드바 현장 배지)은 layout 에 있어 클라이언트 네비게이션으로는 다시 그려지지
      // 않는다 — 방금 등록한 현장이 반영되도록 서버 렌더를 한 번 요청한다. 이걸 빼면
      // "등록했는데 좌측 건수는 그대로"가 되어 등록이 실패한 것처럼 보인다.
      router.refresh();
    } catch {
      setSubmitError("요청을 처리하지 못했습니다.");
      setSubmitPhase("error");
    }
  }

  const draftClearedForSuccess = currentStep === 2 && submitPhase === "success";
  useEffect(() => {
    if (draftClearedForSuccess) clearDraft();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 성공 진입 1회만 정리하면 된다
  }, [draftClearedForSuccess]);

  const trimmedSiteId = form.siteId.trim();
  const jurisdictionRequired = form.egressChoice !== "unset";
  const stepValid: Record<number, boolean> = {
    0:
      (mode === "MAPPED_BOOTSTRAP" ||
        (trimmedSiteId.length > 0 && SITE_ID_PATTERN.test(trimmedSiteId))) &&
      form.name.trim().length > 0 &&
      (!jurisdictionRequired || form.jurisdiction.trim().length > 0),
    1:
      form.aoi.length >= 3 &&
      isConvexPolygon(form.aoi) &&
      form.crs.trim().length > 0 &&
      form.verticalDatum.trim().length > 0 &&
      form.transformVersion.trim().length > 0,
    2: submitPhase !== "pending",
  };

  function handleBack() {
    setCurrentStep((step) => {
      if (step === 1 || step === 2) {
        setSubmitPhase("idle");
        setSubmitError(null);
      }
      return step - 1;
    });
  }

  function handleNext() {
    if (currentStep === 2) {
      if (submitPhase === "success") {
        const siteId = mode === "MAPPED_BOOTSTRAP" ? registeredSiteId : trimmedSiteId;
        if (siteId) router.push(`/sites/${encodeURIComponent(siteId)}`);
      } else {
        void runSubmission();
      }
      return;
    }
    setCurrentStep((step) => step + 1);
  }

  const canGoBack = currentStep > 0 && !(currentStep === 2 && submitPhase === "pending");

  let nextLabel = "다음";
  if (currentStep === 2) {
    nextLabel =
      submitPhase === "success"
        ? "현장 브리핑으로 이동"
        : submitPhase === "error"
          ? "다시 시도"
          : "현장 등록";
  }

  const siteIdError =
    trimmedSiteId.length > 0 && !SITE_ID_PATTERN.test(trimmedSiteId)
      ? "영숫자로 시작하고 이후 영숫자·-·_·. 만 쓸 수 있습니다(공백·/ 금지)."
      : undefined;

  // 값이 비어 다음 버튼이 막혔을 때 그 이유를 말한다(F16) — 필드별 실시간 에러는
  // 여전히 값이 있고 형식이 틀렸을 때만 보인다(위 siteIdError 주석과 같은 원칙).
  const step0DisabledReason = stepValid[0]
    ? undefined
    : mode === "LEGACY_SITE_ID"
      ? !trimmedSiteId
        ? "현장 ID를 입력하세요."
        : siteIdError
          ? siteIdError
          : !form.name.trim()
            ? "현장 이름을 입력하세요."
            : jurisdictionRequired && !form.jurisdiction.trim()
              ? "데이터 반출 여부에 따른 관할을 선택하세요."
              : undefined
      : !form.name.trim()
        ? "현장 이름을 입력하세요."
        : jurisdictionRequired && !form.jurisdiction.trim()
          ? "데이터 반출 여부에 따른 관할을 선택하세요."
          : undefined;

  return (
    <WizardShell
      title="현장 등록"
      stepLabels={STEP_LABELS}
      currentStep={currentStep}
      onBack={canGoBack ? handleBack : undefined}
      onNext={handleNext}
      nextLabel={nextLabel}
      nextDisabled={!stepValid[currentStep]}
      nextDisabledReason={currentStep === 0 ? step0DisabledReason : undefined}
      nextPending={currentStep === 2 && submitPhase === "pending"}
      error={currentStep === 2 && submitError ? <ErrorState message={submitError} /> : undefined}
      exitHref="/sites"
    >
      {currentStep === 0 && (
        <>
          <p className="text-sm break-keep text-ink-2 sm:col-span-2">
            현장 정보와 조사할 공사 구역을 먼저 등록합니다. 첫 조사는 등록 후 현장
            브리핑에서 별도로 계획합니다.
          </p>
          <Field label="현장 이름" required>
            <input
              type="text"
              value={form.name}
              onChange={(event) => update({ name: event.target.value })}
              placeholder="예: OO산업단지 3공구 신축공사 현장"
              className={inputClassName}
            />
          </Field>
          {mode === "LEGACY_SITE_ID" && (
            <Field
              label="현장 ID"
              helpText="자동으로 만들며, 필요하면 바꿀 수 있습니다. 영문·숫자로 시작하고 하이픈(-), 밑줄(_), 점(.)만 쓸 수 있습니다. 공백과 슬래시(/)는 쓸 수 없습니다."
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
          )}

          <fieldset className="flex flex-col gap-2 sm:col-span-2">
            <legend className="text-[12.5px] font-semibold break-keep text-ink-1">
              외부 클라우드 처리
            </legend>
            <p className="text-[11.5px] break-keep text-ink-muted">
              현장 데이터를 승인된 외부 클라우드에서 처리해도 되는지 선택합니다. 사내 정책
              확인이 필요하면 지금 정하지 않아도 되며, 미정 상태에서는 외부로 보내지 않습니다.
            </p>
            {EGRESS_CHOICE_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`tap-target flex items-center gap-2 rounded-md border px-3 py-2 text-sm break-keep ${
                  form.egressChoice === opt.value
                    ? "border-accent bg-accent-tint"
                    : "border-line-strong bg-surface"
                }`}
              >
                <input
                  type="radio"
                  name="egress-choice-only"
                  value={opt.value}
                  checked={form.egressChoice === opt.value}
                  onChange={() => update({ egressChoice: opt.value })}
                />
                {opt.label}
              </label>
            ))}
          </fieldset>

          {jurisdictionRequired && (
            <Field
              label="데이터 처리 기준 지역"
              helpText="대한민국을 기준으로 한다면 KR을 입력하세요."
              required
            >
              <input
                type="text"
                value={form.jurisdiction}
                onChange={(event) => update({ jurisdiction: event.target.value })}
                placeholder="KR"
                className={inputClassName}
              />
            </Field>
          )}

          <label className="tap-target flex items-start gap-2 rounded-md border border-line-strong bg-surface px-3 py-3 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={form.aiEgressAllowed}
              onChange={(event) => update({ aiEgressAllowed: event.target.checked })}
              className="mt-0.5"
            />
            <span>
              <span className="block font-semibold">KSI AI가 구조화된 현장 결과를 읽도록 허용</span>
              <span className="mt-1 block text-[11.5px] leading-5 break-keep text-ink-muted">
                원본 사진은 외부 AI로 보내지 않습니다. 선택하지 않으면 KSI AI 대화를 사용하지 않습니다.
              </span>
            </span>
          </label>
        </>
      )}

      {currentStep === 1 && (
        <>
          <div className="flex flex-col gap-3 sm:col-span-2">
            <p className="text-sm break-keep text-ink-2">
              지도에서 조사할 공사 구역을 그리세요. 최소 3개 꼭짓점의 볼록한 모양이어야 합니다.
            </p>
            <AoiPolygonMap value={form.aoi} onChange={(aoi) => update({ aoi })} />
            {form.aoi.length >= 3 && !isConvexPolygon(form.aoi) && (
              <p className="text-sm break-keep text-high-ink">
                현재 조사 경로는 오목한 외곽을 지원하지 않습니다. 볼록한 외곽으로 다시 그려 주세요.
              </p>
            )}
          </div>
          <Field label="현장 좌표계" helpText="국내 중부 현장은 보통 EPSG:5186을 사용합니다." required>
            <input
              type="text"
              value={form.crs}
              onChange={(event) => update({ crs: event.target.value })}
              placeholder="EPSG:5186"
              className={inputClassName}
            />
          </Field>
          <Field label="높이 기준" helpText="예: KNGeoid2018" required>
            <input
              type="text"
              value={form.verticalDatum}
              onChange={(event) => update({ verticalDatum: event.target.value })}
              placeholder="KNGeoid2018"
              className={inputClassName}
            />
          </Field>
          <Field label="거리 단위" helpText="현재는 미터로 고정됩니다.">
            <input type="text" value="meter" disabled className={inputClassName} />
          </Field>
          <Field label="좌표 설정 버전" helpText="기본값을 유지해도 됩니다.">
            <input
              type="text"
              value={form.transformVersion}
              onChange={(event) => update({ transformVersion: event.target.value })}
              className={inputClassName}
            />
          </Field>
        </>
      )}

      {currentStep === 2 && (
        <>
          {submitPhase === "idle" && (
            <section className="flex flex-col gap-3 rounded-lg border border-line bg-sunk p-4 text-sm sm:col-span-2">
              <h2 className="font-semibold break-keep">등록 내용을 확인하세요</h2>
              <dl className="grid gap-2 sm:grid-cols-2">
                <div><dt className="text-[11.5px] text-ink-muted">현장</dt><dd className="font-medium">{form.name.trim()}</dd></div>
                {mode === "LEGACY_SITE_ID" && (
                  <div><dt className="text-[11.5px] text-ink-muted">현장 ID</dt><dd className="num break-token">{trimmedSiteId}</dd></div>
                )}
                <div><dt className="text-[11.5px] text-ink-muted">현장 범위</dt><dd>{form.aoi.length}개 꼭짓점</dd></div>
                <div><dt className="text-[11.5px] text-ink-muted">현장 좌표계</dt><dd className="num break-token">{form.crs.trim()}</dd></div>
                <div><dt className="text-[11.5px] text-ink-muted">KSI AI</dt><dd>{form.aiEgressAllowed ? "구조화 결과 반출 허용" : "사용 안 함"}</dd></div>
              </dl>
              <p className="text-[12px] break-keep text-ink-2">
                등록 뒤 현장 브리핑에서 첫 조사를 별도로 계획합니다. 이 단계에서는 비행을 시작하지 않습니다.
              </p>
            </section>
          )}
          {submitPhase === "pending" && (
            <p className="text-sm break-keep text-ink-2 sm:col-span-2">현장을 등록하는 중입니다…</p>
          )}
          {submitPhase === "success" && (
            <div className="flex flex-col gap-3 rounded-lg border border-safe/30 bg-safe-bg p-4 text-sm sm:col-span-2">
              <p className="font-medium break-keep text-safe-ink">
                현장이 등록되었습니다.
              </p>
              {/* 링크를 여기서 걸지 않는다 — 아래 "현장 상세로 이동" 버튼(다음 버튼)이
                  이미 같은 목적지로 보낸다. ADR-KSI-015 이후 이 흐름을 고른 사용자도
                  MISSIONS_ISSUE 를 갖고 있어(권한이 아니라 순서를 미룬 것뿐이다),
                  상세 화면에서 "베이스라인 조사 계획" 버튼이 곧바로 보인다. */}
              <p className="break-keep text-safe-ink/90">
                {mode === "MAPPED_BOOTSTRAP"
                  ? "현장 브리핑에서 사용할 수 있는 작업을 확인하세요."
                  : <>첫 조사는 아직 만들어지지 않았습니다. 현장 브리핑에서
                    &quot;베이스라인 조사 계획&quot;으로 이어서 진행할 수 있습니다.</>}
              </p>
            </div>
          )}
          {submitPhase === "error" && (
            <p className="text-sm break-keep text-ink-2 sm:col-span-2">
              처리 중 문제가 발생했습니다. 아래에서 원인을 확인하고 다시 시도하세요.
            </p>
          )}
        </>
      )}
    </WizardShell>
  );
}
