import "server-only";

import { whoAmI } from "./auth";
import type { Permission } from "./types";

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
