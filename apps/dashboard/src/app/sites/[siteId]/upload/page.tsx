import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { continuityFingerprint } from "@/lib/core-api/work-order-continuity";
import { SITE_DETAIL_DOCUMENT_TITLE } from "@/lib/site-detail-title";

import { UploadScreen } from "./UploadScreen";

// 문서 head는 현장 이름·식별자를 싣지 않는다.
export const metadata: Metadata = { title: SITE_DETAIL_DOCUMENT_TITLE };

type Query = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined): string | undefined => (Array.isArray(value) ? value[0] : value);

async function load(siteId: string) {
  try {
    const [site, areas, identity] = await Promise.all([getSite(siteId), listWorkAreas(siteId), whoAmI().catch(() => null)]);
    // 서버가 확인한 두 식별자의 비교값이다. 신원이 없으면 올리기를 시작하지 않는다.
    const fingerprint = continuityFingerprint(identity);
    const permissions = identity?.permissions;
    const verified = Array.isArray(permissions) && permissions.every((permission) => typeof permission === "string");
    return {
      kind: "ready" as const,
      site,
      areas: areas.workAreas.filter((area) => area.status === "ACTIVE"),
      canWrite: verified && permissions.includes("WORK_ORDERS_WRITE"),
      accountIdentity: fingerprint && verified ? { fingerprint } : null,
    };
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) return { kind: "not-found" as const };
    return {
      kind: "error" as const,
      message: error instanceof CoreApiError ? humanizeApiError(error.code, error.status, error.serverMessage) : "자료 올리기에 필요한 현장 정보를 불러오지 못했습니다.",
    };
  }
}

/**
 * 한 화면 올리기 — 작업을 먼저 만들지 않고 파일을 놓고 촬영 시각만 정하면 올린다.
 * 작업·신고·봉인은 화면이 뒤에서 기존 Core 계약대로 만든다. 새 권한·판정은 없다.
 */
export default async function SiteUploadPage({ params, searchParams }: { params: Promise<{ siteId: string }>; searchParams: Promise<Query> }) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const result = await load(siteId);
  if (result.kind === "not-found") notFound();
  if (result.kind === "error") return <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5"><ErrorState message={result.message} retryable /></div>;
  if (!result.canWrite) {
    return <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5"><EmptyState title="자료를 올릴 권한이 없습니다" description="작업 등록 권한이 있는 계정으로 다시 시도하세요." action={{ label: "현장으로 돌아가기", href: `/sites/${encodeURIComponent(siteId)}` }} /></div>;
  }
  return (
    <UploadScreen
      key={first(query.workAreaId) ?? ""}
      siteId={result.site.siteId}
      siteName={result.site.name}
      workAreas={result.areas.map((area) => ({ workAreaId: area.workAreaId, name: area.name, polygon: area.polygon }))}
      initialWorkAreaId={first(query.workAreaId) ?? null}
      accountIdentity={result.accountIdentity}
    />
  );
}
