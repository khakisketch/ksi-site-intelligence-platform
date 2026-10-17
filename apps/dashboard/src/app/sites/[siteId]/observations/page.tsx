import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { listSiteExternalVolumeHistory } from "@/lib/core-api/external-result-workflow";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";

import { ExternalObservationHistory } from "./ExternalObservationHistory";

export const metadata = { title: "외부 관측 이력 · KSI" };

export default async function SiteObservationHistoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ after?: string }>;
}) {
  const { siteId } = await params;
  const { after } = await searchParams;
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return <OperationsSessionFailure
      verdict={session.verdict}
      next={`/sites/${encodeURIComponent(siteId)}/observations`}
    />;
  }
  // Establish Site access before dependent reads. Their absence/denial cannot
  // establish Site absence, and a faster child error must not mask a scoped404.
  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="외부 관측 이력을 불러오지 못했습니다." retryable /></div>;
  }
  let loaded: {
    history: Awaited<ReturnType<typeof listSiteExternalVolumeHistory>>;
    areas: Awaited<ReturnType<typeof listWorkAreas>>;
  } | null = null;
  let denied = false;
  let retryAfterSeconds: number | undefined;
  try {
    const [history, areas] = await Promise.all([
      listSiteExternalVolumeHistory(siteId, { after, limit: 50 }),
      listWorkAreas(siteId),
    ]);
    loaded = { history, areas };
  } catch (error) {
    denied = error instanceof CoreApiError && error.status === 403;
    retryAfterSeconds = error instanceof CoreApiError ? error.retryAfterSeconds : undefined;
  }
  const names = new Map(loaded?.areas.workAreas.map((area) => [area.workAreaId, area.name]));
  return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">
    <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
      <div>
        <p className="text-[12.5px] text-ink-2">{site.name}</p>
        <h2 className="mt-1 text-[22px] font-bold tracking-tight">외부 관측 결과 이력</h2>
        <p className="mt-1 text-[13px] leading-5 text-ink-2">보관 근거가 확인된 외부 비교 기록을 표시합니다. Core 분석 기록(V2)은 현장 분석에서 확인하며, 두 기록의 계산·권위를 합치지 않습니다.</p>
      </div>
      <div className="flex flex-wrap gap-2"><Link href={`/sites/${encodeURIComponent(siteId)}/analysis`} className="btn">현장 분석</Link><Link href={`/sites/${encodeURIComponent(siteId)}/spatial-assets`} className="btn">공간 자산</Link><Link href={`/sites/${encodeURIComponent(siteId)}`} className="btn">현장으로 돌아가기</Link></div>
    </header>
    {loaded ? <ExternalObservationHistory siteId={siteId} items={loaded.history.items} workAreaNames={names} /> :
      <ErrorState message={denied ? "외부 관측 이력을 조회할 권한이 없습니다. 현장 담당자에게 조회 권한을 요청하세요." : "외부 관측 이력을 불러오지 못했습니다."} tone={denied ? "high" : "crit"} retryable={!denied} retryAfterSeconds={retryAfterSeconds} />}
    {loaded?.history.nextCursor && <Link className="btn w-fit" href={`/sites/${encodeURIComponent(siteId)}/observations?after=${encodeURIComponent(loaded.history.nextCursor)}`}>이전 결과 더 보기</Link>}
  </div>;
}
