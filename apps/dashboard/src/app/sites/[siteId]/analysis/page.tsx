import Link from "next/link";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { getAnalysis, listAnalyses, listAnalysisObservations } from "@/lib/core-api/analysis";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";

import { AnalysisRequestPanel } from "./AnalysisRequestPanel";

export const metadata = { title: "현장 분석 · KSI" };

export default async function SiteAnalysisPage({ params, searchParams }: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ analysisId?: string }>;
}) {
  const [{ siteId }, { analysisId }] = await Promise.all([params, searchParams]);
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={`/sites/${encodeURIComponent(siteId)}/analysis`} />;
  let loaded: {
    site: Awaited<ReturnType<typeof getSite>>;
    areas: Awaited<ReturnType<typeof listWorkAreas>>;
    observations: Awaited<ReturnType<typeof listAnalysisObservations>>;
    analyses: Awaited<ReturnType<typeof listAnalyses>>;
    selectedDetail: Awaited<ReturnType<typeof getAnalysis>> | null;
  } | null = null;
  try {
    const [site, areas, observations, listedAnalyses] = await Promise.all([
      getSite(siteId),
      listWorkAreas(siteId),
      listAnalysisObservations(siteId),
      listAnalyses(siteId, { limit: 50 }),
    ]);
    const detail = analysisId && !listedAnalyses.items.some((item) => item.analysisId === analysisId)
      ? await getAnalysis(siteId, analysisId)
      : null;
    loaded = { site, areas, observations, analyses: listedAnalyses, selectedDetail: detail };
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
  }
  if (loaded === null) return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="현장 분석 정보를 불러오지 못했습니다." retryable /></div>;
  return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5"><header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3"><div><p className="text-[12.5px] text-ink-2">{loaded.site.name}</p><h1 className="mt-1 text-[22px] font-bold tracking-tight">현장 분석</h1><p className="mt-1 text-[13px] leading-5 text-ink-2">같은 작업구역의 두 외부 관측을 선택해 Core의 분석 기록과 근거를 확인합니다.</p></div><Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="btn">외부 관측 이력</Link></header><AnalysisRequestPanel siteId={siteId} organizationId={session.principal.organizationId} principalId={session.principal.principalId} workAreas={loaded.areas.workAreas} observations={loaded.observations} initialPage={loaded.analyses} initialSelectedDetail={loaded.selectedDetail} canCreate={session.principal.permissions.includes("SITES_WRITE")} initialAnalysisId={analysisId ?? null} /></div>;
}
