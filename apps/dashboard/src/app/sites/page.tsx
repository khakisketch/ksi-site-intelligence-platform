import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError, SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { listSites } from "@/lib/core-api/sites";
import type { SiteView } from "@/lib/core-api/types";

const dateFormatter = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" });

function PageHeader() {
  return (
    <div className="flex items-center justify-between gap-4">
      <h1 className="text-lg font-semibold break-keep">현장</h1>
      {/* 등록 동선은 목록 상태와 무관하게 상시 노출(UX 목표 §2 "현장 상태 확인" 예산과 별개). */}
      <Link
        href="/sites/new"
        className="bg-foreground text-background inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium"
      >
        현장 등록
      </Link>
    </div>
  );
}

export default async function SitesPage() {
  // 데이터 조회는 JSX 생성과 분리한다 — try/catch 안에서 JSX 를 만들면
  // eslint react-hooks/error-boundaries 가 걸린다(렌더는 즉시 실행되지 않아 실제로 못 잡는 에러다).
  let sites: SiteView[] | null = null;
  let errorMessage: string | null = null;
  try {
    sites = await listSites();
  } catch (error) {
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-6 sm:p-10">
      <PageHeader />
      {errorMessage !== null ? (
        <ErrorState message={errorMessage} />
      ) : sites !== null && sites.length === 0 ? (
        <EmptyState
          title="아직 등록된 현장이 없습니다"
          action={{ label: "현장 등록", href: "/sites/new" }}
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {sites?.map((site) => {
            const statusLabel = SITE_STATUS_LABEL[site.status];
            return (
              <li key={site.siteId}>
                <Link
                  href={`/sites/${encodeURIComponent(site.siteId)}`}
                  className="flex min-h-11 flex-col gap-2 rounded-lg border border-black/10 px-4 py-3 transition-colors hover:bg-black/5 dark:border-white/10 dark:hover:bg-white/5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex flex-col gap-1">
                    <span className="break-keep font-medium">{site.name}</span>
                    <span className="text-foreground/60 text-xs">{site.siteId}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <StatusBadge label={statusLabel.label} tone={statusLabel.tone} />
                    <span className="text-foreground/60 text-xs whitespace-nowrap">
                      갱신 {dateFormatter.format(new Date(site.updatedAt))}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
