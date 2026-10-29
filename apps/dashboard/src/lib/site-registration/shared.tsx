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
 * 레거시 siteId POST의 원래 요청 보존 — **409 하나만으로 소유권을 확정하지
 * 않기 위한** 최소 결속이다.
 *
 * - `observedSuccess`: 같은 세션에서 이 siteId·이 원본으로 2xx를 **관측**한
 *   적이 있다는 기록일 뿐, 소유권 증명이 아니다. 클라이언트는 계정·조직을 알
 *   수 없고(Core 응답에 귀속이 없고 세션 토큰은 httpOnly라 읽을 수 없다),
 *   계정 전환 뒤의 409는 다른 조직의 같은 ID일 수 있다. 그래서 관측 성공 뒤의
 *   409도 자동 성공으로 승격하지 않고 수동 확인으로만 푼다.
 * - `payloadDigest`: 그 시도가 보낸 본문의 지문(이름·AOI·좌표계·반출 선언 등).
 *   재시도 전에 입력이 바뀌면 원래 요청의 재시도가 아니므로 그 사실까지 밝힌다.
 */

/** 레거시 siteId POST 시도 기록 — 성공 판정의 근거가 아니라 확인 안내의 재료다. */
export interface SitePostAttempt {
  siteId: string;
  payloadDigest: string;
  observedSuccess: boolean;
}

export interface SitePostPayloadInput {
  name: string;
  aoi: unknown;
  crs: string;
  verticalDatum: string;
  transformVersion: string;
  egressChoice: unknown;
  jurisdiction: string;
  aiEgressAllowed: boolean;
}

/** 원래 요청의 지문 — 키 순서 고정 JSON. 크면 비교만 하면 되므로 해시하지 않는다. */
export function digestSitePostPayload(input: SitePostPayloadInput): string {
  return JSON.stringify({
    aiEgressAllowed: input.aiEgressAllowed,
    aoi: input.aoi,
    crs: input.crs,
    egressChoice: input.egressChoice,
    jurisdiction: input.jurisdiction,
    name: input.name,
    transformVersion: input.transformVersion,
    verticalDatum: input.verticalDatum,
  });
}

export function buildSitePostAttempt(
  siteId: string,
  payload: SitePostPayloadInput,
  observedSuccess: boolean,
): SitePostAttempt {
  return { siteId, payloadDigest: digestSitePostPayload(payload), observedSuccess };
}

/**
 * 레거시 siteId POST 판정 — **자동 성공 경로가 없다.**
 *
 * - `success`: 2xx + 응답의 siteId가 요청 ID와 일치할 때뿐이다.
 * - `duplicateUnverified`: 409 DUPLICATE_SITE_ID. 첫 충돌이든 관측 성공 뒤든,
 *   계정 일치가 확인되지 않으므로 소유권을 확정하지 않고 목록·상세 수동 확인으로
 *   안내한다. `sameSiteAsPrevious`·`payloadChanged`는 안내 문구의 재료일 뿐
 *   성공 근거가 아니다.
 * - `definiteFailure`: BFF 로컬(400)·인증/인가(401/403)·요청 검증(422)뿐이다.
 *   레거시 등록 경로가 Core에서 404를 낼 수 없으므로 404도 unknown이다.
 * - `unknown`: 그 밖 전부(네트워크 예외·408/429·5xx 전체·알 수 없는 4xx·2xx 본문
 *   불일치). 코드가 있다는 이유만으로 '쓰기 안 됨'을 단정하지 않는다.
 */
export type LegacySitePostOutcome =
  | { kind: "success" }
  | { kind: "duplicateUnverified"; sameSiteAsPrevious: boolean; payloadChanged: boolean }
  | { kind: "unknown" }
  | { kind: "definiteFailure" };
export function classifyLegacySitePost(input: {
  fetchThrew: boolean;
  status: number | null;
  bodyCode: string | null;
  /** 2xx 응답에서 읽은 site.siteId(없으면 null). */
  responseSiteId: string | null;
  requestedSiteId: string;
  previous: SitePostAttempt | null;
  payloadDigest: string;
}): LegacySitePostOutcome {
  if (input.fetchThrew || input.status === null) {
    return { kind: "unknown" };
  }
  const { status, requestedSiteId } = input;
  if (status >= 200 && status < 300) {
    return input.responseSiteId !== null &&
      input.responseSiteId !== "" &&
      input.responseSiteId === requestedSiteId
      ? { kind: "success" }
      : { kind: "unknown" };
  }
  if (status === 409 && input.bodyCode === "DUPLICATE_SITE_ID") {
    const sameSiteAsPrevious = input.previous?.siteId === requestedSiteId;
    return {
      kind: "duplicateUnverified",
      sameSiteAsPrevious,
      payloadChanged: sameSiteAsPrevious
        ? input.previous!.payloadDigest !== input.payloadDigest
        : false,
    };
  }
  if (status === 400 || status === 401 || status === 403 || status === 422) {
    return { kind: "definiteFailure" };
  }
  return { kind: "unknown" };
}

/**
 * 2xx 성공 응답의 정직한 결속 — "서버가 무엇을 만들었는가"를 보낸 원본과 대조한다.
 *
 * 실제 계약 근거(BFF·Core 실측, 지어내지 않음):
 * - BFF `POST /api/sites`는 Core `POST /v1/sites`의 2xx를 `{ site: SiteView }`로
 *   그대로 싣는다(`registerSite`는 non-ok에서 throw하므로 BFF 2xx ⇒ Core 201
 *   REGISTERED — 다른 verdict는 전부 4xx·5xx로 throw된다). `verdict` 필드 자체는
 *   BFF가 싣지 않으므로 결속은 `site` 내용으로만 한다.
 * - Core는 등록 필드를 **정규화하지 않고 그대로 저장**한다
 *   (`SiteStore._register_locked`: siteId·name은 비공백 검사만, siteFrame·aoi·
 *   dataResidency는 검증된 모델의 `model_dump` 그대로). trim·소문자화·반올림이
 *   없으므로 응답의 저장 필드는 보낸 값과 **엄격 일치**해야 한다. 다르면 서버가
 *   다른 내용을 만들었거나(또는 응답이 깨졌거나) 한 것이니 성공이 아니다.
 * - 결속 대상(=저장 가능 필드): siteId·name·siteFrame(crs·verticalDatum·unit·
 *   transformVersion)·aoi.vertices·dataResidency·aiEgressAllowed.
 *   `status`(UNMAPPED 등)·`registeredAt`·`updatedAt`·`resumeTarget`·
 *   `modelMaxAgeDays`·`spatialModel`은 서버가 정하는 파생값이라 결속하지 않는다.
 * - `requestedSiteId`가 null이면 mapped bootstrap 경로다 — 서버가 `site-uuid4`
 *   형태를 발급하므로 그 모양(기존 SITE_ID_PATTERN + `site-` 접두)만 요구하고,
 *   나머지는 동일하게 대조한다.
 * - 어느 하나라도 어긋나면 `false`다 — 성공·실패 어느 쪽으로도 단정하지 않고
 *   호출부는 unknown(확인 필요)으로만 안내한다.
 */
export interface SitePostEchoExpectation {
  /** 레거시: 요청한 siteId. mapped bootstrap(서버 발급): null. */
  requestedSiteId: string | null;
  /** 보낸 이름(trimmed 그대로 — Core는 trim하지 않는다). */
  name: string;
  siteFrame: { crs: string; verticalDatum: string; unit: string; transformVersion: string };
  /** 보낸 꼭짓점 배열 그대로(`{latDeg, lonDeg}[]` — Core는 값을 바꾸지 않는다). */
  aoiVertices: unknown;
  /** 보낸 dataResidency — `undefined`는 키 생략(미선언)이라 응답 null과 결속한다. */
  dataResidency: { egressAllowed: boolean; jurisdiction: string } | undefined;
  aiEgressAllowed: boolean;
}

export function verifySitePostEcho(
  responseSite: unknown,
  expected: SitePostEchoExpectation,
): { ok: true; siteId: string } | { ok: false } {
  if (!responseSite || typeof responseSite !== "object" || Array.isArray(responseSite)) {
    return { ok: false };
  }
  const site = responseSite as Record<string, unknown>;

  const siteId = site.siteId;
  if (typeof siteId !== "string" || siteId.length === 0) return { ok: false };
  if (expected.requestedSiteId !== null) {
    // 레거시: 요청 ID와 엄격 일치 — 다른 ID는 다른 현장이다.
    if (siteId !== expected.requestedSiteId) return { ok: false };
  } else if (!siteId.startsWith("site-") || !SITE_ID_PATTERN.test(siteId)) {
    // mapped: 서버 발급 모양이 아니면(빈 값·다른 체계) 성공이 아니다.
    return { ok: false };
  }

  // 이름 — Core는 비공백 검사만 하고 그대로 저장한다.
  if (site.name !== expected.name) return { ok: false };

  // 좌표계 — 4개 필드 엄격 일치. 여분 키는 관대히 무시한다(서버 확장 대비).
  const frame = site.siteFrame;
  if (!frame || typeof frame !== "object" || Array.isArray(frame)) return { ok: false };
  const frameRecord = frame as Record<string, unknown>;
  if (
    frameRecord.crs !== expected.siteFrame.crs ||
    frameRecord.verticalDatum !== expected.siteFrame.verticalDatum ||
    frameRecord.unit !== expected.siteFrame.unit ||
    frameRecord.transformVersion !== expected.siteFrame.transformVersion
  ) {
    return { ok: false };
  }

  // 현장 범위 — 꼭짓점 수와 각 좌표 엄격 일치(JSON 왕복은 배정밀도를 보존한다).
  const aoi = site.aoi;
  if (!aoi || typeof aoi !== "object" || Array.isArray(aoi)) return { ok: false };
  const vertices = (aoi as Record<string, unknown>).vertices;
  if (!Array.isArray(vertices) || !Array.isArray(expected.aoiVertices)) return { ok: false };
  if (vertices.length !== expected.aoiVertices.length) return { ok: false };
  for (let index = 0; index < vertices.length; index += 1) {
    const actual = vertices[index] as Record<string, unknown> | null;
    const wanted = expected.aoiVertices[index] as Record<string, unknown> | null;
    if (!actual || typeof actual !== "object" || !wanted || typeof wanted !== "object") {
      return { ok: false };
    }
    if (actual.latDeg !== wanted.latDeg || actual.lonDeg !== wanted.lonDeg) return { ok: false };
  }

  // 반출 선언 — 생략(미선언)은 응답 null과 결속한다(INV-050 fail-closed).
  // null이 "허용"으로 읽히면 안 되므로, 생략을 보냈는데 객체가 오면 성공이 아니다.
  // 키 자체가 빠진 것은 미선언이 아니라 비정상 본문이다 — Core wire는 None을
  // 항상 null로 싣기(응답 모델이 None을 포함 직렬화) 때문에 누락은 unknown이다.
  if (!("dataResidency" in site)) return { ok: false };
  const dataResidency = (site as Record<string, unknown>).dataResidency ?? null;
  if (expected.dataResidency === undefined) {
    if (dataResidency !== null) return { ok: false };
  } else {
    if (!dataResidency || typeof dataResidency !== "object" || Array.isArray(dataResidency)) {
      return { ok: false };
    }
    const residency = dataResidency as Record<string, unknown>;
    if (
      residency.egressAllowed !== expected.dataResidency.egressAllowed ||
      residency.jurisdiction !== expected.dataResidency.jurisdiction
    ) {
      return { ok: false };
    }
  }

  if (site.aiEgressAllowed !== expected.aiEgressAllowed) return { ok: false };

  return { ok: true, siteId };
}

/**
 * 확인되지 않은 이전 요청 목록 — "모른다"를 파기하지 않기 위한 fail-closed 기록이다.
 *
 * - 키 회전·계정 교체·성공이 이전 불명을 지우지 않는다. 검증된 성공은 자기
 *   (kind, key, origin, digest) 항목만 제거하고 나머지는 남긴다.
 * - `originFingerprint`는 그 시도의 원래 신원이다. 현재 세션과 다르면 이름 등
 *   상세 표시는 계정 일치 때만 한다(목록 자체는 파기하지 않는다).
 * - draft에 함께 저장되므로 같은 탭 remount 뒤에도 유지된다. 성공 후 이동 때도
 *   남긴다. 용량을 이유로 조용히 버리지 않는다 — 상한(`MAX_PRIOR_UNKNOWNS`)에
 *   도달하면 신규 변이를 보내기 전에 차단하고, 사용자가 목록 확인 뒤 명시적으로
 *   기록을 지우게 한다(삭제에는 손실 고지가 따른다).
 * - Core bootstrap 멱등 범위는 (organization, actor, requestKey)라 key만으로는
 *   전역 유일하지 않다. 같은 key라도 원래 신원이 다르면 별개 기록으로 보존하고,
 *   어느 한쪽의 성공·삭제가 타 주체 항목을 지우거나 귀속을 바꾸지 않는다.
 *   원래 신원이 미상인 항목은 원문을 유지한 채 잠그고(표시·삭제·귀속 모두 금지),
 *   절대 다른 계정의 것으로 추측하지 않는다.
 */
export interface PriorUnknownRequest {
  kind: "mapped" | "legacy";
  /** mapped: bootstrapRequestId, legacy: siteId. */
  key: string;
  originFingerprint?: string;
  payloadDigest: string;
  name: string;
}

/**
 * 미해결 불명이 이 개수에 도달하면 신규 POST를 보내기 전 차단한다.
 * 잘라내기 상한이 아니다 — 기록을 조용히 버리는 데 쓰지 않는다.
 * 개수는 (kind, key, origin, digest) 서로 다른 기록 기준이다.
 */
export const MAX_PRIOR_UNKNOWNS = 5;

export function isValidPriorUnknown(value: unknown): value is PriorUnknownRequest {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  if (candidate.kind !== "mapped" && candidate.kind !== "legacy") return false;
  if (typeof candidate.key !== "string" || candidate.key.length === 0) return false;
  if (
    candidate.originFingerprint !== undefined &&
    (typeof candidate.originFingerprint !== "string" ||
      !/^v1-[0-9a-f]{64}$/.test(candidate.originFingerprint))
  ) {
    return false;
  }
  if (typeof candidate.payloadDigest !== "string" || typeof candidate.name !== "string") {
    return false;
  }
  return true;
}

/**
 * 같은 (kind, key, origin, digest)는 정확히 같은 요청의 재시도이므로 하나로
 * 합치고 최신을 앞에 둔다. 조용히 버리지 않는다.
 *
 * 결속 단위는 (kind, key, originFingerprint, payloadDigest)이다. Core bootstrap
 * 멱등 범위가 (organization, actor, requestKey)이므로 key만으로는 요청을 구분할
 * 수 없고, 같은 주체가 같은 키로 내용을 바꿔 보내면 서로 다른 미확인 요청이다
 * (예: 불명 X 뒤 같은 siteId로 Y를 보내 또 불명). digest가 다르면 별개 기록으로
 * 나란히 보존한다(어느 쪽도 다른 쪽을 덮어쓰거나 지우지 않는다).
 */
export function upsertPriorUnknown(
  list: PriorUnknownRequest[] | undefined,
  entry: PriorUnknownRequest,
): PriorUnknownRequest[] {
  const sameBinding = (item: PriorUnknownRequest): boolean =>
    item.kind === entry.kind &&
    item.key === entry.key &&
    (item.originFingerprint ?? null) === (entry.originFingerprint ?? null) &&
    item.payloadDigest === entry.payloadDigest;
  const rest = (list ?? []).filter((item) => !sameBinding(item));
  return [entry, ...rest];
}

/**
 * (kind, key, origin, digest)가 정확히 일치하는 항목만 제거한다. 검증된 성공과
 * 명시 삭제는 자기 원본의 그 요청만 해소한다 — 같은 키의 다른 내용·다른 주체
 * 항목은 남긴다.
 */
export function removePriorUnknown(
  list: PriorUnknownRequest[] | undefined,
  kind: PriorUnknownRequest["kind"],
  key: string,
  origin: string,
  payloadDigest: string,
): PriorUnknownRequest[] {
  return (list ?? []).filter(
    (item) =>
      !(
        item.kind === kind &&
        item.key === key &&
        (item.originFingerprint ?? null) === (origin ?? null) &&
        item.payloadDigest === payloadDigest
      ),
  );
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
