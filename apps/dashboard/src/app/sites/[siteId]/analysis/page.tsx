import Link from "next/link";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { getAnalysis, listAnalyses, listAnalysisObservations } from "@/lib/core-api/analysis";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";

import { AnalysisStartGuide } from "./AnalysisStartGuide";
import { AnalysisRequestPanel } from "./AnalysisRequestPanel";

export const metadata = { title: "현장 분석 · KSI" };

export default async function SiteAnalysisPage({ params, searchParams }: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ analysisId?: string }>;
}) {
  const [{ siteId }, { analysisId }] = await Promise.all([params, searchParams]);
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={`/sites/${encodeURIComponent(siteId)}/analysis`} />;
  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    // A Site 404 is the only response that establishes this route as unavailable.
    // Child analysis routes can be absent in a local graph while the Site itself
    // remains readable; resolve the scoped Site before asking for those children.
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="현장 접근을 확인하지 못했습니다." retryable /></div>;
  }

  let loaded: {
    areas: Awaited<ReturnType<typeof listWorkAreas>>;
    observations: Awaited<ReturnType<typeof listAnalysisObservations>>;
    attributedObservations: (Awaited<ReturnType<typeof listAnalysisObservations>>[number] & { workAreaIds: string[] })[];
    unattributedObservationCount: number;
    analyses: Awaited<ReturnType<typeof listAnalyses>>;
    selectedDetail: Awaited<ReturnType<typeof getAnalysis>> | null;
  } | null = null;
  let childError: unknown;
  try {
    const [areas, observations, listedAnalyses, workOrders] = await Promise.all([
      listWorkAreas(siteId),
      listAnalysisObservations(siteId),
      listAnalyses(siteId, { limit: 50 }),
      listObservationWorkOrders(siteId).catch(() => null),
    ]);
    const detail = analysisId && !listedAnalyses.items.some((item) => item.analysisId === analysisId)
      ? await getAnalysis(siteId, analysisId)
      : null;
    const workAreasByOrder = new Map<string, string[]>();
    for (const order of workOrders ?? []) {
      if (order.siteId !== siteId || order.organizationId !== session.principal.organizationId) continue;
      const workAreaIds = Array.isArray(order.workAreaIds)
        ? [...new Set(order.workAreaIds.filter((id): id is string => typeof id === "string" && id.length > 0))]
        : [];
      if (workAreaIds.length > 0) workAreasByOrder.set(order.workOrderId, workAreaIds);
    }
    let unattributedObservationCount = 0;
    const attributedObservations = observations.flatMap((observation) => {
      const workAreaIds = workAreasByOrder.get(observation.selector.workOrderId);
      if (!workAreaIds) {
        unattributedObservationCount += 1;
        return [];
      }
      return [{ ...observation, workAreaIds }];
    });
    loaded = { areas, observations, attributedObservations, unattributedObservationCount, analyses: listedAnalyses, selectedDetail: detail };
  } catch (error) {
    childError = error;
  }
  const unavailable = childError instanceof CoreApiError && childError.status === 404;
  const denied = childError instanceof CoreApiError && childError.status === 403;
  const retryAfterSeconds = childError instanceof CoreApiError ? childError.retryAfterSeconds : undefined;
  const canCreate = session.principal.permissions.includes("SITES_WRITE");
  return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">
    <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
      <div>
        <p className="text-[12.5px] text-ink-2">{site.name}</p>
        <h2 className="mt-1 text-[22px] font-bold tracking-tight">현장 분석</h2>
        <p className="mt-1 text-[13px] leading-5 text-ink-2">같은 작업구역의 두 외부 관측을 선택해 Core의 분석 기록과 근거를 확인합니다.</p>
      </div>
      <Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="btn">외부 관측 이력</Link>
    </header>
    {loaded ? <>
      <AnalysisStartGuide
        siteId={siteId}
        workAreaCount={loaded.areas.workAreas.length}
        observationCount={loaded.attributedObservations.length}
        analysisCount={loaded.analyses.items.length}
        hasMoreAnalyses={loaded.analyses.nextCursor !== null}
        canCreate={canCreate}
      />
      <AnalysisRequestPanel
        siteId={siteId}
        organizationId={session.principal.organizationId}
        principalId={session.principal.principalId}
        workAreas={loaded.areas.workAreas}
        observations={loaded.attributedObservations}
        unattributedObservationCount={loaded.unattributedObservationCount}
        initialPage={loaded.analyses}
        initialSelectedDetail={loaded.selectedDetail}
        canCreate={canCreate}
        initialAnalysisId={analysisId ?? null}
      />
    </> : <ErrorState message={denied ? "현장 분석을 조회할 권한이 없습니다. 현장 담당자에게 분석 기록 조회 권한을 요청하세요." : unavailable ? "이 환경에서는 현장 분석 기능을 사용할 수 없습니다." : "현장 분석 정보를 불러오지 못했습니다."} tone={denied ? "high" : unavailable ? "idle" : "crit"} retryable={!denied && !unavailable} retryAfterSeconds={retryAfterSeconds} />}
  </div>;
}
