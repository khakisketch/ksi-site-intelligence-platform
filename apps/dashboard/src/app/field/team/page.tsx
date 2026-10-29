import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { listOrganizationWorkRoster } from "@/lib/core-api/work-collaboration";
import { continuityFingerprint } from "@/lib/core-api/work-order-continuity";

import { OperationsSessionFailure } from "../OperationsSessionFailure";
import { resolveFieldSession } from "../resolve-session";
import { FieldWorkNav } from "../FieldWorkNav";
import { TeamRosterPanel } from "./TeamRosterPanel";
import { describeTeamReadError } from "./team-read-error";

export const metadata = { title: "팀 관리 · KSI" };

export default async function FieldTeamPage() {
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next="/field/team" />;
  const canManage = session.principal.role === "ADMIN";
  let roster: Awaited<ReturnType<typeof listOrganizationWorkRoster>> | null = null;
  try {
    roster = await listOrganizationWorkRoster({ includeInactive: canManage });
  } catch (error) {
    if (error instanceof CoreApiError) {
      const presentation = describeTeamReadError(error);
      return <div className="p-4 sm:p-5"><ErrorState message={presentation.message} detail={presentation.detail} retryable={presentation.retryable} retryAfterSeconds={presentation.retryAfterSeconds} tone={presentation.tone} action={presentation.action} /></div>;
    }
    throw error;
  }
  // 팀원 저장 재시도의 계정 연속성 비교값 — 서버에서 확인한 두 식별자의
  // 비교값일 뿐 자격 증명이나 인가가 아니다. 확인값이 없으면 이 화면은 새
  // 저장을 막는다. 무헤더 BFF 호환은 다른 호출자에게만 남는다. 조직 ID는
  // 응답 범위 검증을 위해 전달하며 자격 증명이 아니다.
  const accountIdentity = (() => {
    const fingerprint = continuityFingerprint(session.principal);
    const permissions = session.principal.permissions;
    const permissionsVerified = Array.isArray(permissions) && permissions.every((permission) => typeof permission === "string");
    return fingerprint && permissionsVerified ? { fingerprint } : null;
  })();
  return <div className="console-page"><FieldWorkNav active="team" showTeam /> <header><h2 className="console-page-title">팀 관리</h2><p className="console-page-description">작업 배정·공유에 쓰는 팀원 정보입니다. 계정 권한은 변경하지 않습니다.</p></header><div className="w-full max-w-4xl"><TeamRosterPanel initialMembers={roster.members} canManage={canManage} currentPrincipalId={session.principal.principalId} organizationId={session.principal.organizationId} accountIdentity={accountIdentity} /></div></div>;
}
