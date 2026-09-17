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
  let loaded: {
    site: Awaited<ReturnType<typeof getSite>>;
    history: Awaited<ReturnType<typeof listSiteExternalVolumeHistory>>;
    areas: Awaited<ReturnType<typeof listWorkAreas>>;
  } | null = null;
  try {
    const [site, history, areas] = await Promise.all([
      getSite(siteId),
      listSiteExternalVolumeHistory(siteId, { after, limit: 50 }),
      listWorkAreas(siteId),
    ]);
    loaded = { site, history, areas };
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
  }
  if (loaded === null) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="외부 관측 이력을 불러오지 못했습니다." retryable /></div>;
  }
  const names = new Map(loaded.areas.workAreas.map((area) => [area.workAreaId, area.name]));
  return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">
    <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
      <div>
        <p className="text-[12.5px] text-ink-2">{loaded.site.name}</p>
        <h1 className="mt-1 text-[22px] font-bold tracking-tight">외부 관측 결과 이력</h1>
        <p className="mt-1 text-[13px] leading-5 text-ink-2">보관 근거가 확인된 결과만 수치와 추이를 표시합니다.</p>
      </div>
      <Link href={`/sites/${encodeURIComponent(siteId)}`} className="btn">현장으로 돌아가기</Link>
    </header>
    <ExternalObservationHistory siteId={siteId} items={loaded.history.items} workAreaNames={names} />
    {loaded.history.nextCursor && <Link className="btn w-fit" href={`/sites/${encodeURIComponent(siteId)}/observations?after=${encodeURIComponent(loaded.history.nextCursor)}`}>이전 결과 더 보기</Link>}
  </div>;
}
