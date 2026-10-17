import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { listWorkInbox } from "@/lib/core-api/work-collaboration";
import { resolveWorkInboxContext } from "@/lib/work-inbox-context";

import { OperationsSessionFailure } from "../OperationsSessionFailure";
import { resolveFieldSession } from "../resolve-session";
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
  return <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-4 sm:p-5"><header><h2 className="text-[22px] font-bold tracking-tight">받은 업무</h2><p className="mt-1 text-[13px] leading-5 text-ink-2">배정된 작업과 공유된 결과를 확인합니다. 대상 접근 권한은 열 때 다시 확인됩니다.</p></header><WorkInboxPanel initialItems={inbox.items} initialNextCursor={inbox.nextCursor} initialUnreadOnly={unreadOnly} initialContextByRef={contextByRef} /></div>;
}
