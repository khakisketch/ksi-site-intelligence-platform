import Link from "next/link";
import { notFound } from "next/navigation";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getSite } from "@/lib/core-api/sites";
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
}: {
  params: Promise<{ siteId: string }>;
}) {
  const { siteId } = await params;

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
  const [workAreasResult, canWriteResult] = await Promise.allSettled([
    listWorkAreas(site.siteId, { includeArchived: true }),
    hasAllPermissions("SITES_WRITE"),
  ]);
  const workAreas: WorkArea[] =
    workAreasResult.status === "fulfilled" ? workAreasResult.value.workAreas : [];
  const workAreaError =
    workAreasResult.status === "rejected" ? workAreaListFailure(workAreasResult.reason) : null;
  const canWrite = canWriteResult.status === "fulfilled" && canWriteResult.value;

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <Link
          href={`/sites/${encodeURIComponent(site.siteId)}`}
          className="text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
        >
          ← {site.name}
        </Link>
        <h2 className="break-keep text-[19px] font-bold tracking-tight">작업구역</h2>
        <p className="max-w-2xl text-[12.5px] break-keep text-ink-2">
          두 시점의 관측 변화를 같은 범위에서 반복 비교하기 위한 구역입니다. 한 번
          등록해 두면 이후 비교할 때마다 지도에 새로 그리는 대신 이 구역을{" "}
          <strong className="font-bold">고르기만</strong> 하면 됩니다.
        </p>
        <p className="max-w-2xl text-[12.5px] break-keep text-ink-muted">
          그래서 <strong className="font-bold">한 번 등록한 모양은 고칠 수 없습니다</strong> —
          잘못 그렸다면 대신할 구역을 새로 등록하세요(이전 구역은 자동으로 보관되고, 이미 낸
          리포트는 그때의 범위를 그대로 가리킵니다). 등록은 범위 고정일 뿐, 계획 대비
          진척·정확도·분석 가능 여부·사람 검토를 증명하지 않습니다.
        </p>
      </div>

      <WorkAreaPanel
        siteId={site.siteId}
        siteCrs={site.siteFrame.crs}
        canWrite={canWrite}
        initialWorkAreas={workAreas}
        workAreaListError={workAreaError}
      />
    </div>
  );
}
