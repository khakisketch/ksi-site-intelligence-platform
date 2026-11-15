import { ROLE_LABEL } from "@/lib/core-api/labels";

import { AccountMenu } from "./AccountMenu";
import { readShellPrincipal } from "./shell-principal";

/**
 * 레일 아래쪽의 계정 자리(768px 이상). 신원을 못 읽으면 아무것도 그리지 않는다 —
 * 만료·거절·연결 실패의 안내와 복구 행동은 상단바(TopBar)가 이미 맡고 있다.
 */
export async function RailAccount() {
  const principal = await readShellPrincipal().catch(() => null);
  if (!principal) return null;
  return (
    <AccountMenu
      placement="rail"
      principalId={principal.principalId}
      roleLabel={principal.role ? ROLE_LABEL[principal.role] : principal.kind}
    />
  );
}
