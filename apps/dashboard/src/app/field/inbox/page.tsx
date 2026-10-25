import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { listWorkInbox } from "@/lib/core-api/work-collaboration";
import { resolveWorkInboxContext } from "@/lib/work-inbox-context";

import { OperationsSessionFailure } from "../OperationsSessionFailure";
import { resolveFieldSession } from "../resolve-session";
import { FieldWorkNav } from "../FieldWorkNav";
import { WorkInboxPanel } from "./WorkInboxPanel";

export const metadata = { title: "받은 업무 · KSI" };

export default async function FieldInboxPage({ searchParams }: { searchParams: Promise<{ unread?: string }> }) {
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next="/field/inbox" />;
  const { unread } = await searchParams;
  const unreadOnly = unread !== "false";
  let inbox: Awaited<ReturnType<typeof listWorkInbox>> | null = null;
  try {
    inbox = await listWorkInbox({ unreadOnly });
  } catch (error) {
    if (error instanceof CoreApiError) return <div className="p-4 sm:p-5"><ErrorState message="받은 업무를 불러오지 못했습니다." retryable /></div>;
    throw error;
  }
  // 첫 화면 항목의 맥락 이름만 서버에서 한 번에 확인한다(중복 제거·병렬, 실패 무시).
  const contextByRef = await resolveWorkInboxContext(inbox.items).catch(() => ({}));
  const showTeam = session.principal.role === "ADMIN" || session.principal.permissions.includes("WORK_ORDERS_WRITE");
  return <div className="console-page"><FieldWorkNav active="inbox" showTeam={showTeam} /><header><h2 className="console-page-title">받은 업무</h2><p className="console-page-description">나에게 배정된 작업과 공유된 결과입니다.</p></header><WorkInboxPanel initialItems={inbox.items} initialNextCursor={inbox.nextCursor} initialUnreadOnly={unreadOnly} initialContextByRef={contextByRef} /></div>;
}
