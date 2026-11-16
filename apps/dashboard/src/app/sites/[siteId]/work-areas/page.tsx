import { redirect } from "next/navigation";

import { siteAreasHref } from "@/components/nav/site-context";

import { parseScopeId } from "../site-spatial";

/**
 * 작업구역 화면은 공간의 영역 관리 보기로 옮겼다(ADR-KSI-043).
 * 옛 주소·안내 링크가 계속 열리도록 그대로 보내며, 고를 영역 힌트는 새 화면이 서버 목록과 다시 대조한다.
 */
export default async function SiteWorkAreasPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams?: Promise<{ workAreaId?: string | string[] }>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams ?? Promise.resolve({})]);
  const requested = parseScopeId("workAreaId" in query && typeof query.workAreaId === "string" ? query.workAreaId : null);
  redirect(siteAreasHref(siteId, requested, { manage: true }));
}
