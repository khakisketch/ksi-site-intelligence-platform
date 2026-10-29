import "server-only";

import { whoAmI } from "./auth";
import { CoreApiError } from "./client";
import { MissingSessionError } from "./session";
import type { Permission, WhoAmIResponse } from "./types";
import { continuityFingerprint } from "./work-order-continuity";

/**
 * 로그인 주체가 주어진 권한을 전부 가지고 있는지 확인한다. 세션이 없거나 무효면 false —
 * 호출부에서 별도 에러 처리를 하지 않아도 되게 fail-closed 로 답한다.
 *
 * risk dashboard-wizard-rbac-mismatch — SiteRegistrationWizard/SurveyWizard 처럼 여러
 * Core 엔드포인트를 잇는 흐름은 권한이 하나라도 없으면 중간에서 끊겨 반쪽 상태(예:
 * 현장은 등록됐는데 임무는 미발급)를 남긴다. 진입 자체를 막아 그 상태를 예방한다
 * (권한표 자체를 바꾸는 게 아니다 — 그건 공동 결정 레인, 여기선 UI 방어만 한다).
 */
export async function hasAllPermissions(...perms: Permission[]): Promise<boolean> {
  try {
    const principal = await whoAmI();
    return perms.every((p) => principal.permissions.includes(p));
  } catch {
    return false;
  }
}

/**
 * F-01 현장 등록 모드 — Core whoami 의 registry metadata 로만 판정한다.
 *
 * - `MAPPED_BOOTSTRAP`: registry 발급 신원 + SITE_BOOTSTRAP + SITES_WRITE.
 *   서버 발급 siteId 계약(bootstrapRequestId)을 써야 하고, 은퇴한 MISSIONS_ISSUE
 *   를 등록 전제로 요구하지 않는다.
 * - `LEGACY_SITE_ID`: 기존 opaque 계약(SITES_WRITE + MISSIONS_ISSUE) — 그대로.
 * - `DENIED`: 그 외 전부. **registry 신원인데 capability 가 없으면 legacy 로
 *   되돌아가지 않는다** — mapped 신원의 siteId 형태는 Core 가 422 로 거부하므로
 *   legacy 진입은 반쪽 성공을 부른다(fail-closed).
 */
export type SiteRegistrationMode = "MAPPED_BOOTSTRAP" | "LEGACY_SITE_ID" | "DENIED";

export function resolveSiteRegistrationMode(
  principal: Pick<WhoAmIResponse, "permissions" | "registryScoped" | "capabilities">,
): SiteRegistrationMode {
  const canWrite = principal.permissions.includes("SITES_WRITE");
  if (principal.registryScoped === true) {
    return canWrite && principal.capabilities?.includes("SITE_BOOTSTRAP") === true
      ? "MAPPED_BOOTSTRAP"
      : "DENIED";
  }
  return canWrite && principal.permissions.includes("MISSIONS_ISSUE")
    ? "LEGACY_SITE_ID"
    : "DENIED";
}

/** whoami 실패(세션 없음·Core 장애)는 DENIED — 진입을 열지 않는다. */
export async function getSiteRegistrationMode(): Promise<SiteRegistrationMode> {
  try {
    return resolveSiteRegistrationMode(await whoAmI());
  } catch {
    return "DENIED";
  }
}

/**
 * 현장 등록 게이트의 3상태 읽기. INV-040(정직한 unavailable) — 예전에는 whoami
 * 실패를 전부 DENIED 로 뭉뚱그려 "권한 없음"으로만 보였다.
 *
 * - `allowed` — 등록 가능 모드 그대로(MAPPED_BOOTSTRAP | LEGACY_SITE_ID).
 * - `denied` — 확정된 거부: 권한 부족 판정, 401/403, 세션 없음. 진입을 닫는다.
 * - `unavailable` — Core 5xx·네트워크 등 확인 자체가 실패. 거짓 거부가 아니라
 *   재시도 가능한 미확인으로 보여준다.
 *
 * INV-060(fail-closed): 셋 중 어느 경우에도 쓰기 계약·RBAC 은 바뀌지 않으며,
 * 이 함수는 읽기 판정만 한다. getSiteRegistrationMode 는 그대로 둔다(호환).
 *
 * `accountFingerprint`는 이 페이지를 렌더한 세션의 서버 확인 신원 지문이다 —
 * 현장 등록 재시도의 계정 연속성 가드가 같은 탭의 원래 신원과 대조하는 재료다.
 * 자격 증명·인가가 아니며 Core 계약·권한을 바꾸지 않는다. 신원을 확인할 수
 * 없으면(allowed인데 지문 계산 실패) null이며, 호출자는 이전 계약(보호 없음)
 * 으로 동작한다.
 */
export type SiteRegistrationAvailability =
  | { status: "allowed"; mode: Exclude<SiteRegistrationMode, "DENIED">; accountFingerprint?: string | null }
  | { status: "denied" }
  | { status: "unavailable" };

export async function getSiteRegistrationAvailability(): Promise<SiteRegistrationAvailability> {
  let principal: WhoAmIResponse;
  try {
    principal = await whoAmI();
  } catch (error) {
    // 진짜 인증 실패(401/403·세션 없음)만 거부다. 나머지는 장애·미확인이다.
    if (error instanceof MissingSessionError) return { status: "denied" };
    if (error instanceof CoreApiError && (error.status === 401 || error.status === 403)) {
      return { status: "denied" };
    }
    return { status: "unavailable" };
  }
  const mode = resolveSiteRegistrationMode(principal);
  if (mode === "DENIED") return { status: "denied" };
  return { status: "allowed", mode, accountFingerprint: continuityFingerprint(principal) };
}
