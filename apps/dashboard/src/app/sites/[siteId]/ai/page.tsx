import Link from "next/link";
import { notFound } from "next/navigation";

import { CoreApiError } from "@/lib/core-api/client";
import {
  getConversation,
  listSiteConversations,
} from "@/lib/core-api/copilot-conversations";
import { getSite } from "@/lib/core-api/sites";
import type { CopilotConversation } from "@/lib/core-api/types";

import { SiteCopilotChat } from "./SiteCopilotChat";

export default async function SiteAiPage({ params }: { params: Promise<{ siteId: string }> }) {
  const { siteId } = await params;
  let site;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    throw error;
  }

  let runtimeAvailable = true;
  let conversations: CopilotConversation[] = [];
  try {
    conversations = (await listSiteConversations(site.siteId)).conversations;
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) runtimeAvailable = false;
    else throw error;
  }
  const initialDetail =
    conversations.length > 0
      ? await getConversation(conversations[0].conversationId).catch(() => null)
      : null;

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={`/sites/${encodeURIComponent(site.siteId)}`} className="tap-target inline-flex items-center text-[13px] underline">
          ← {site.name} 브리핑
        </Link>
      </div>
      <div>
        <h2 className="text-[19px] font-bold tracking-tight">KSI AI · {site.name}</h2>
        <p className="mt-1 text-[12.5px] break-keep text-ink-2">
          현장 원장과 검증된 분석 결과를 근거로 답하며, 확인할 수 없는 내용은 추측하지 않습니다.
        </p>
      </div>
      <SiteCopilotChat
        siteId={site.siteId}
        aiEgressAllowed={site.aiEgressAllowed}
        initialConversations={conversations}
        initialDetail={initialDetail}
        runtimeAvailable={runtimeAvailable}
      />
    </div>
  );
}
