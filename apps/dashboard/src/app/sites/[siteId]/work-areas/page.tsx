import { notFound } from "next/navigation";
import { parseScopeId } from "../site-spatial";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { whoAmI } from "@/lib/core-api/auth";
import { continuityFingerprint } from "@/lib/core-api/work-order-continuity";
import { getSite } from "@/lib/core-api/sites";
import { AccountDisplayBoundary } from "@/components/nav/AccountDisplayBoundary";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { ErrorState } from "@/components/ui/ErrorState";
import type { SiteView, WorkArea } from "@/lib/core-api/types";

import { WorkAreaPanel } from "./WorkAreaPanel";

type WorkAreaListFailure = {
  message: string;
  tone: "crit" | "high" | "idle";
  retryable: boolean;
  retryAfterSeconds?: number;
};

function workAreaListFailure(error: unknown): WorkAreaListFailure {
  if (error instanceof CoreApiError) {
    if (error.status === 401) {
      return { message: "작업구역 목록을 보려면 다시 로그인한 뒤 확인하세요.", tone: "high", retryable: false };
    }
    if (error.status === 403) {
      return { message: "작업구역 목록을 조회할 권한이 없습니다. 현장 담당자에게 조회 권한을 요청하세요.", tone: "high", retryable: false };
    }
    if (error.status === 404) {
      return { message: "현장 작업구역 목록을 확인할 수 없습니다. 현장 담당자에게 접근 권한과 작업구역 설정을 확인해 달라고 요청하세요.", tone: "idle", retryable: false };
    }
    if (error.status >= 500) {
      return { message: "Core에서 작업구역 목록을 일시적으로 불러오지 못했습니다.", tone: "crit", retryable: true, retryAfterSeconds: error.retryAfterSeconds };
    }
    return { message: "작업구역 목록 요청을 처리할 수 없습니다. 현장 정보와 접근 권한을 확인하세요.", tone: "high", retryable: false };
  }
  return { message: "작업구역 목록을 불러오지 못했습니다. 다시 시도하세요.", tone: "crit", retryable: true };
}

/**
 * 작업구역 등록 화면 — "지난주와 이번주가 같은 범위인가"를 성립시키는 자리(M4-C).
 *
 * 비교할 때마다 지도에 폴리곤을 새로 그리면 매번 범위가 조금씩 달라지고, 그러면
 * 두 시점의 숫자를 나란히 놓을 수 없다. 한 번 이름과 함께 등록해 두면 이후에는
 * 고르기만 한다.
 *
 * 그 대가로 **기하는 등록 순간 굳는다** — 이 화면에 수정 버튼이 없는 이유다.
 * 이미 그 구역으로 낸 리포트가 가리키는 범위가 사후에 바뀌면 안 된다.
 *
 * 등록은 범위 고정일 뿐이다 — 공정·계획 대비 진척, 정확도, 분석 가능 여부,
 * 사람 검토를 증명하지 않는다(ADR037 상대 관측 지형 변화의 한계와 같다).
 */
export default async function SiteWorkAreasPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams?: Promise<{ workAreaId?: string | string[] }>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams ?? Promise.resolve({})]);
  const requestedArea = parseScopeId("workAreaId" in query && typeof query.workAreaId === "string" ? query.workAreaId : null);

  let site: SiteView | null = null;
  let errorMessage: string | null = null;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  if (errorMessage !== null || site === null) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState message={errorMessage ?? "요청을 처리하지 못했습니다."} />
      </div>
    );
  }

  // 목록·권한 조회는 서로 독립이다 — 목록이 실패해도 등록 폼은 살아 있어야 한다.
  // 보관된 것까지 함께 읽는다: 이 화면은 "고를 수 있는 것"을 고르는 자리가 아니라
  // 현장의 구역 이력을 관리하는 자리다(무엇이 무엇을 대신했는지가 여기 남는다).
  // 계정 연속성 확인값도 함께 읽는다 — 서버에서 확인한 두 식별자의 비교값일 뿐
  // 자격 증명이나 인가가 아니다. 페이지와 현재 계정을 확인하지 못하면
  // 패널은 목록과 원문을 숨기고 재확인을 안내한다. 쓰기 요청은 별도 BFF 가드도 쓴다.
  const [workAreasResult, canWriteResult, canCreateWorkOrderResult, identityResult] = await Promise.allSettled([
    listWorkAreas(site.siteId, { includeArchived: true }),
    hasAllPermissions("SITES_WRITE"),
    hasAllPermissions("WORK_ORDERS_WRITE"),
    whoAmI().catch(() => null),
  ]);
  const workAreas: WorkArea[] =
    workAreasResult.status === "fulfilled" ? workAreasResult.value.workAreas : [];
  const workAreaError =
    workAreasResult.status === "rejected" ? workAreaListFailure(workAreasResult.reason) : null;
  const canWrite = canWriteResult.status === "fulfilled" && canWriteResult.value;
  const canCreateWorkOrder = canCreateWorkOrderResult.status === "fulfilled" && canCreateWorkOrderResult.value;
  const identity = identityResult.status === "fulfilled" ? identityResult.value : null;
  // Core가 principal에 경로 안전 형식을 강제하지 않으므로, 서버에서 정확한 두
  // 식별자의 ASCII 비교값을 만들고 원문 식별자는 클라이언트에 내보내지 않는다.
  const accountIdentity = (() => {
    const fingerprint = continuityFingerprint(identity);
    const permissions = identity?.permissions;
    const permissionsVerified =
      Array.isArray(permissions) && permissions.every((permission) => typeof permission === "string");
    return fingerprint && permissionsVerified ? { fingerprint } : null;
  })();

  return (
    <AccountDisplayBoundary fingerprint={accountIdentity?.fingerprint ?? null}>
    <div className="flex flex-col">
      <SiteHeader
        site={site}
        selectedEpochId={null}
        tab="manage"
        scopedWorkAreaId={workAreas.some((area) => area.workAreaId === requestedArea) ? requestedArea : null}
        canCreateWorkOrder={canCreateWorkOrder}
        canEditAoi={canWrite}
      />
      <div className="flex flex-col gap-5 p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <h2 className="break-keep text-[19px] font-bold tracking-tight">작업구역</h2>
        <p className="max-w-2xl text-[12.5px] break-keep text-ink-2">
          비교할 범위를 이름과 함께 등록합니다. 이후 관측 자료를 같은 구역에 연결해 변화를 확인할 수 있습니다.
        </p>
        <p className="max-w-2xl text-[12.5px] break-keep text-ink-muted">
          등록한 경계는 그대로 보존합니다. 범위를 바꾸려면 새 구역으로 대체하며, 기존 결과는 이전 구역을 계속 참조합니다.
          구역 등록만으로 정확도나 분석 가능 여부가 확인되지는 않습니다.
        </p>
      </div>

      <WorkAreaPanel
        siteId={site.siteId}
        siteCrs={site.siteFrame.crs}
        canWrite={canWrite}
        initialWorkAreas={workAreas}
        workAreaListError={workAreaError}
        accountIdentity={accountIdentity}
      />
      </div>
    </div>
    </AccountDisplayBoundary>
  );
}
