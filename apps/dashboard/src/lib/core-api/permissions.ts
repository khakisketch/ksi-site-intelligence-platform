import "server-only";

import { whoAmI } from "./auth";
import type { Permission, WhoAmIResponse } from "./types";

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
