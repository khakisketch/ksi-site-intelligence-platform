import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { listOrganizationWorkRoster } from "@/lib/core-api/work-collaboration";

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
  return <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-4 sm:p-5"><FieldWorkNav active="team" showTeam /> <header><h2 className="text-[22px] font-bold tracking-tight">팀 관리</h2><p className="mt-1 text-[13px] leading-5 text-ink-2">작업 배정·공유에 쓰는 팀원 정보를 확인합니다. 조직 관리 화면이 아닙니다.</p></header><TeamRosterPanel initialMembers={roster.members} canManage={canManage} currentPrincipalId={session.principal.principalId} /></div>;
}
