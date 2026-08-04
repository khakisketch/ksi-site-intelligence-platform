"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { WizardShell } from "@/components/wizard/WizardShell";
import { ErrorState } from "@/components/ui/ErrorState";
import { useDraftState } from "@/hooks/useDraftState";
import type { SiteFrame } from "@/lib/core-api/types";

// risk dashboard-wizard-rbac-mismatch 해소 — SiteRegistrationWizard(등록+baseline 임무
// 발급을 한 흐름으로 처리)는 SITES_WRITE 와 MISSIONS_ISSUE 를 동시에 요구해 그 조합을
// 가진 role이 ADMIN뿐이었다. 이 컴포넌트는 SITES_WRITE 만 가진 role(SITE_MANAGER 등)이
// 현장 등록까지만 끝내는 축약 흐름이다 — AOI·매핑 파라미터는 순수 임무 발급 소관이라
// 여기서는 아예 묻지 않는다(등록 시점엔 저장할 곳이 없어 어차피 버려진다). baseline
// 임무는 MISSIONS_ISSUE 를 가진 role이 나중에 /sites/[siteId]/surveys/new 에서
// "초기 매핑(베이스라인)" 목적으로 발급한다(SurveyWizard.tsx buildPurposeOptions 참조).
// Site 상태머신은 UNMAPPED 를 정상 중간 상태로 이미 설계해 두었다(등록 즉시 baseline
// 발급을 강제하지 않는다) — 대표자 확인 완료.
const STEP_LABELS = ["기본정보", "좌표계", "완료"];

interface FormState {
  siteId: string;
  name: string;
  crs: string;
  verticalDatum: string;
  transformVersion: string;
}

const INITIAL_FORM: FormState = {
  siteId: "",
  name: "",
  crs: "",
  verticalDatum: "",
  transformVersion: "1.0.0",
};

const SITE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

const inputClassName = "input";

function Field({
  label,
  helpText,
  error,
  required,
  children,
}: {
  label: string;
  helpText?: string;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    // label 이 입력을 **감싼다** — htmlFor/id 짝 대신 암묵적 연결을 쓴다. 형제로 두면
    // 접근가능 이름이 placeholder 로 잡히는데(2026-08-04 렌더 확인에서 실제 재현:
    // "현장 ID" 가 아니라 "영숫자로 시작, -/_/. 만 허용…"), placeholder 는 입력을 시작하면
    // 사라져서 스크린리더 사용자가 필드 이름을 잃는다. help/error 는 label 밖에 둔다 —
    // 안에 넣으면 이름에 합쳐져 이름이 문단만큼 길어진다.
    <div className="flex flex-col gap-1.5">
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

async function parseJsonSafe(res: Response): Promise<{ message?: string; code?: string }> {
  try {
    return (await res.json()) as { message?: string; code?: string };
  } catch {
    return {};
  }
}

type SubmitPhase = "idle" | "pending" | "error" | "success";

export function SiteRegistrationOnlyWizard() {
  const router = useRouter();
  const [form, setForm, clearDraft] = useDraftState<FormState>(
    "ksi-wizard-site-registration-only",
    INITIAL_FORM,
  );
  const [currentStep, setCurrentStep] = useState(0);
  const [submitPhase, setSubmitPhase] = useState<SubmitPhase>("idle");
  const [submitError, setSubmitError] = useState<string | null>(null);

  function update(partial: Partial<FormState>) {
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
      const res = await fetch("/api/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ siteId, name: form.name.trim(), siteFrame }),
      });
      if (!res.ok) {
        const body = await parseJsonSafe(res);
        // 재시도(네트워크 순간 단절 등)로 이미 등록된 뒤 다시 온 경우도 성공으로 본다 —
        // SiteRegistrationWizard.tsx 와 동일 관례.
        const alreadyRegistered = res.status === 409 && body.code === "DUPLICATE_SITE_ID";
        if (!alreadyRegistered) {
          setSubmitError(body.message ?? "요청을 처리하지 못했습니다.");
          setSubmitPhase("error");
          return;
        }
      }
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

  // "완료" 단계(2) 진입 시 자동으로 등록을 시작한다(다른 Wizard와 동일 관례 — spec §7).
  useEffect(() => {
    if (currentStep === 2 && submitPhase === "idle") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 외부 API 호출(fetch) 트리거, 순수 파생 state 아님
      void runSubmission();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 최신 form 은 클로저로 캡처, currentStep 전이에만 반응
  }, [currentStep]);

  const draftClearedForSuccess = currentStep === 2 && submitPhase === "success";
  useEffect(() => {
    if (draftClearedForSuccess) clearDraft();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 성공 진입 1회만 정리하면 된다
  }, [draftClearedForSuccess]);

  const trimmedSiteId = form.siteId.trim();
  const stepValid: Record<number, boolean> = {
    0: trimmedSiteId.length > 0 && SITE_ID_PATTERN.test(trimmedSiteId) && form.name.trim().length > 0,
    1:
      form.crs.trim().length > 0 &&
      form.verticalDatum.trim().length > 0 &&
      form.transformVersion.trim().length > 0,
    2: submitPhase !== "pending",
  };

  function handleBack() {
    setCurrentStep((step) => {
      if (step === 1) {
        setSubmitPhase("idle");
        setSubmitError(null);
      }
      return step - 1;
    });
  }

  function handleNext() {
    if (currentStep === 2) {
      if (submitPhase === "success") {
        router.push(`/sites/${encodeURIComponent(trimmedSiteId)}`);
      } else {
        void runSubmission();
      }
      return;
    }
    setCurrentStep((step) => step + 1);
  }

  const canGoBack = currentStep > 0 && !(currentStep === 2 && submitPhase === "pending");

  let nextLabel = "다음";
  if (currentStep === 1) {
    nextLabel = "등록";
  } else if (currentStep === 2) {
    nextLabel = submitPhase === "success" ? "현장 상세로 이동" : "다시 시도";
  }

  const siteIdError =
    trimmedSiteId.length > 0 && !SITE_ID_PATTERN.test(trimmedSiteId)
      ? "영숫자로 시작하고 이후 영숫자·-·_·. 만 쓸 수 있습니다(공백·/ 금지)."
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
      nextPending={currentStep === 2 && submitPhase === "pending"}
      error={currentStep === 2 && submitError ? <ErrorState message={submitError} /> : undefined}
      exitHref="/sites"
    >
      {currentStep === 0 && (
        <>
          <p className="text-sm break-keep text-ink-2 sm:col-span-2">
            이 계정은 현장 등록 권한만 있어 등록까지만 진행합니다. 베이스라인 임무 발급은 발급
            권한을 가진 담당자가 나중에 진행합니다.
          </p>
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
        </>
      )}

      {currentStep === 2 && (
        <>
          {submitPhase === "pending" && (
            <p className="text-sm break-keep text-ink-2 sm:col-span-2">현장을 등록하는 중입니다…</p>
          )}
          {submitPhase === "success" && (
            <div className="flex flex-col gap-3 rounded-lg border border-safe/30 bg-safe-bg p-4 text-sm sm:col-span-2">
              <p className="font-medium break-keep text-safe-ink">
                현장이 등록되었습니다.
              </p>
              <p className="break-keep text-safe-ink/90">
                베이스라인 임무는 아직 발급되지 않았습니다 — 임무 발급 권한을 가진 담당자가 현장
                상세 화면의{" "}
                <Link
                  href={`/sites/${encodeURIComponent(trimmedSiteId)}/surveys/new`}
                  className="underline"
                >
                  새 조사
                </Link>
                에서 &quot;초기 매핑(베이스라인)&quot;을 선택해 발급할 수 있습니다.
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
