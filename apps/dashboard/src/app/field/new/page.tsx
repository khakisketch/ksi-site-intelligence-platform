import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { listSitesCached } from "@/lib/core-api/cached";
import { CoreApiError } from "@/lib/core-api/client";
import { SITE_STATUS_LABEL, humanizeApiError } from "@/lib/core-api/labels";

import { OperationsSessionFailure } from "../OperationsSessionFailure";
import { resolveFieldSession } from "../resolve-session";

async function fetchSitesForNewObservation() {
  try {
    return { sites: await listSitesCached(), error: null };
  } catch (error) {
    return {
      sites: null,
      error: error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "현장 목록을 불러오지 못했습니다.",
    };
  }
}

export default async function FieldNewObservationPage() {
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return <OperationsSessionFailure verdict={session.verdict} next="/field/new" />;
  }
  if (!session.principal.permissions.includes("WORK_ORDERS_WRITE")) {
    return <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5"><EmptyState title="새 관측을 등록할 권한이 없습니다" description="작업 등록 권한이 있는 계정으로 다시 시도하세요." action={{ label: "작업으로 돌아가기", href: "/field" }} /></div>;
  }

  const result = await fetchSitesForNewObservation();
  if (result.error !== null) {
    return <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5"><ErrorState message={result.error} retryable /></div>;
  }
  const sites = result.sites;
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5">
      <div>
        <p className="text-[12.5px] text-ink-2">새 관측은 현장의 작업구역과 함께 시작합니다.</p>
        <h2 className="mt-1 text-[22px] font-bold tracking-tight">현장 선택</h2>
      </div>
      {sites.length === 0 ? (
        <EmptyState title="선택할 현장이 없습니다" description="먼저 현장을 등록한 뒤 관측을 시작하세요." />
      ) : (
        <ul className="flex flex-col divide-y divide-line rounded-xl border border-line bg-surface px-4">
          {sites.map((site) => <li key={site.siteId}>
            <Link href={`/sites/${encodeURIComponent(site.siteId)}/observations/new`} className="tap-target -mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-3 hover:bg-sunk">
              <span className="min-w-0 flex flex-col gap-1">
                <span className="block text-[14px] font-semibold">{site.name}</span>
                <StateBadge label={SITE_STATUS_LABEL[site.status].label} tone={SITE_STATUS_LABEL[site.status].tone} />
              </span>
              <span className="text-[13px] font-bold whitespace-nowrap text-accent-text">선택 ›</span>
            </Link>
          </li>)}
        </ul>
      )}
    </div>
  );
}
