import type { EgressChoice } from "@/lib/data-residency";

// SiteRegistrationOnlyWizard 와 SiteRegistrationWizard 가 공유하는 순수 로직·
// 프레젠테이션 조각. 두 곳에 각각 복제돼 있었고(Field 의 `wide` prop처럼 drift
// 도 이미 발생했다) 하나로 합친다 — 새 필드·검증 규칙은 여기 한 곳만 고치면 된다.

/** 현장 ID 형식 — 영숫자로 시작, 이후 영숫자·-·_·. 만 허용, 공백·/ 금지. */
export const SITE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export const EGRESS_CHOICE_OPTIONS: Array<{ value: EgressChoice; label: string }> = [
  { value: "unset", label: "지금 정하지 않음 (기본값 — 반출 불가로 처리됩니다)" },
  { value: "allow", label: "예 — 외부/벤더 클라우드 처리를 허용합니다" },
  { value: "deny", label: "아니오 — 사내 서버에서만 처리합니다" },
];

export async function parseJsonSafe(res: Response): Promise<{ message?: string; code?: string }> {
  try {
    return (await res.json()) as { message?: string; code?: string };
  } catch {
    return {};
  }
}

/**
 * POST /v1/sites 의 409(DUPLICATE_SITE_ID)를 "내가 방금 보낸 POST 의 재시도"로
 * 볼지 판정한다.
 *
 * **판정이 성립하는 근거는 "그 siteId 를 이 세션이 보냈다"이다** — 근거는 두
 * 가지이고 둘 다 유효하다:
 *
 * 1. **결과를 모른다**(네트워크 예외·5xx). 서버는 등록했을 수 있으므로 같은
 *    siteId 로 보낸 다음 시도의 409 는 내가 만든 것이다.
 * 2. **성공했다**(2xx). 내가 만든 것이 확실하므로 뒤이은 409 도 내 것이다.
 *
 * 반대로 직전 시도가 **409 응답을 받았다면** 서버가 "이미 있다"고 확정해 준
 * 것이라 그 시점에 내가 만든 것은 없고, 그 뒤의 409 도 여전히 남의 현장이다.
 *
 * 그래서 `ownPostSiteId` 는 위 1·2 에 해당하는 siteId 만 담는다
 * (`nextOwnPostSiteId` 가 그 값을 만든다 — 그쪽 주석이 상세하다). 지금까지
 * 이 판정을 틀린 방식이 셋이고 전부 독립 검토가 잡았다(2026-08-16):
 *
 * - siteId 로 스코프하지 않으면(그냥 boolean): 'A' 로 실패한 뒤 무관한 'B' 로
 *   고쳐 재제출한 409 도 "내 재시도"가 된다.
 * - 확정 409 뒤에도 값을 남겨두면: 남의 'A' 로 한 번 거부당한 사용자가 입력을
 *   그대로 두고 "다시 시도"만 눌러도 두 번째 409 가 "내 재시도"가 된다.
 * - 성공 뒤에 값을 비우면(위 2번을 빠뜨리면): 등록은 됐는데 임무 계획 발급이
 *   실패해 "이전"을 누른 사용자가, 자기가 방금 만든 현장을 "남의 현장"으로
 *   통보받아 정상 재시도가 막힌다.
 *
 * 앞의 두 경우는 저장이 일어나지 않았는데 "현장이 등록되었습니다"가 뜨고, 전체
 * 위저드에서는 그 남의 현장 앞으로 임무 계약 발급까지 이어진다.
 */
export function isRetryOfOwnSitePost(
  ownPostSiteId: string | null,
  siteId: string,
  status: number,
  code: string | undefined,
): boolean {
  return ownPostSiteId === siteId && status === 409 && code === "DUPLICATE_SITE_ID";
}

/**
 * 이번 시도 뒤 ref 에 남길 값 — **"이 세션이 보낸 것으로 쳐서, 뒤이은 409 를
 * 내 것으로 볼 siteId"**.
 *
 * 남기는 경우가 두 가지라는 것이 요점이다:
 *
 * 1. **결과를 모른다**(네트워크 예외·5xx). 서버는 등록했을 수 있다.
 * 2. **성공했다**(2xx). 내가 만든 것이 확실하다 — 전체 위저드에서 사용자가
 *    "이전"을 누르면 `handleBack` 이 `siteRegisteredRef` 만 되돌리므로 같은
 *    siteId 로 재-POST 가 일어나고, 그때 돌아오는 409 는 **1단계에서 내가 만든
 *    그 현장**이다. 여기서 값을 비우면 자기가 만든 현장을 "남의 현장"으로
 *    오판해 정상 재시도가 막힌다(2026-08-16 3차 독립 검토가 적발 — 이 함수를
 *    "결과 모름"으로만 좁게 읽었던 것이 원인이다).
 *
 * 비우는 경우는 하나뿐이다 — **확정 409**. 서버가 "이미 있다"를 확정해 준
 * 시점에 이 시도로 만들어진 것은 없으므로, 그 뒤의 409 도 여전히 남의 현장이다.
 *
 * 호출부는 POST 를 **보내기 전에** ref 를 `siteId` 로 세워두고(중간에 죽어도
 * "모른다"가 기본값이 되게), 응답을 받은 뒤 이 함수의 결과로 덮어쓴다 —
 * 성공·실패 **양쪽 모두** 덮어써야 위 2번이 성립한다.
 */
export function nextOwnPostSiteId(
  siteId: string,
  status: number | null,
  code: string | undefined,
): string | null {
  // 서버가 "이미 있다"고 확정해 줬다 = 이 시도로 만들어진 것은 없다.
  if (status === 409 && code === "DUPLICATE_SITE_ID") return null;
  // 그 밖은 전부 "내가 보낸 것으로 친다" — 성공(내가 만들었다)이든
  // 결과 불명(만들었을 수 있다)이든, 뒤이은 409 는 내 것이다.
  return siteId;
}

export function Field({
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
    // label 이 입력을 **감싼다** — htmlFor/id 짝 대신 암묵적 연결을 쓴다. 형제로 두면
    // 접근가능 이름이 placeholder 로 잡히는데(2026-08-04 렌더 확인에서 실제 재현:
    // "현장 ID" 가 아니라 "영숫자로 시작, -/_/. 만 허용…"), placeholder 는 입력을 시작하면
    // 사라져서 스크린리더 사용자가 필드 이름을 잃는다. help/error 는 label 밖에 둔다 —
    // 안에 넣으면 이름에 합쳐져 이름이 문단만큼 길어진다.
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
