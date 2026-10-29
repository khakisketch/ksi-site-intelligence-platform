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
    return <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5"><EmptyState title="관측 자료를 등록할 권한이 없습니다" description="작업 등록 권한이 있는 계정으로 다시 시도하세요." action={{ label: "작업으로 돌아가기", href: "/field" }} /></div>;
  }

  const result = await fetchSitesForNewObservation();
  if (result.error !== null) {
    return <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5"><ErrorState message={result.error} retryable /></div>;
  }
  const sites = result.sites;
  return (
    <div className="console-page !max-w-[800px]">
      <div>
        <h2 className="console-page-title">어느 현장의 자료인가요?</h2>
        <p className="console-page-description">현장을 고른 뒤 작업구역을 선택합니다.</p>
      </div>
      {sites.length === 0 ? (
        <EmptyState title="현재 계정에서 선택할 수 있는 현장이 없습니다" description="찾는 현장이 이미 있다면 관리자에게 이 계정의 현장 접근 권한을 확인해 주세요." action={{ label: "현장 목록", href: "/sites" }} />
      ) : (
        <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface px-4">
          {sites.map((site) => <li key={site.siteId}>
            <Link href={`/sites/${encodeURIComponent(site.siteId)}/observations/new`} className="tap-target -mx-2 flex items-center justify-between gap-3 rounded-lg px-2 py-3 hover:bg-sunk">
              <span className="min-w-0 flex flex-col items-start gap-1">
                <span className="block text-[14px] font-semibold">{site.name}</span>
                <StateBadge label={SITE_STATUS_LABEL[site.status].label} tone={SITE_STATUS_LABEL[site.status].tone} />
              </span>
              <span className="flex items-center gap-2 text-[13px] font-semibold whitespace-nowrap text-accent-text">선택<svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="size-4"><path d="m7 4 6 6-6 6" /></svg></span>
            </Link>
          </li>)}
        </ul>
      )}
    </div>
  );
}
