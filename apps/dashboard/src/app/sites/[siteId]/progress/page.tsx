import { redirect } from "next/navigation";

import { siteDataHref } from "@/components/nav/site-context";

export const metadata = { title: "자료 · KSI" };

// 옛 등록 진행 주소 — 자료 섹션의 등록 진행 서랍으로 보낸다.
export default async function SiteProgressPage({ params }: { params: Promise<{ siteId: string }> }) {
  const { siteId } = await params;
  redirect(siteDataHref(siteId, { progress: true }));
}
