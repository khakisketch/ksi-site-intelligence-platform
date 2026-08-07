import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listEquipmentStates } from "@/lib/core-api/phase34";
import { formatUncertainty } from "@/lib/core-api/phase34-labels";
import { listSitesCached } from "@/lib/core-api/cached";
import type { EquipmentStateListView, SiteView } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

type Result =
  | { view: EquipmentStateListView; error: null }
  | { view: null; error: CoreApiError };

async function fetchStates(siteId: string): Promise<Result> {
  try {
    return { view: await listEquipmentStates(siteId), error: null };
  } catch (error) {
    if (error instanceof CoreApiError) return { view: null, error };
    throw error;
  }
}

async function fetchSites(): Promise<SiteView[]> {
  try {
    return await listSitesCached();
  } catch {
    return [];
  }
}

function speedOf(velocity: readonly number[]): number {
  return Math.hypot(velocity[0], velocity[1], velocity[2]);
}

/**
 * 2D·3D World — Phase 3 장비·작업자 운동상태 (PRD RISK-002, §26.3).
 *
 * 지금은 **개체별 최신 상태 목록**까지다. 지도 오버레이·3D 뷰는 site_frame 좌표를
 * 화면 좌표로 옮기는 투영이 필요한데, 그 변환은 현장 등록 좌표계(EPSG)와 지도
 * 타일의 관계를 정하는 별도 결정이라 여기서 지어내지 않는다 — 숫자를 정직하게
 * 먼저 보여주고, 투영은 그 결정 뒤에 얹는다.
 *
 * `positionUncertaintyM` 을 매 행에 싣는 이유: 위치만 보여주면 운영자가 그 값을
 * 확정된 사실로 읽는다. 이 값은 공분산 trace 의 제곱근이고 서버가 계산한다.
 *
 * 두 개체의 CPA/TTC 위험 평가는 쌍과 정책 파라미터를 사람이 지목해야 성립하므로
 * (어느 쌍이 평가 대상인지는 이 저장소 어디에도 정해져 있지 않다) 이 목록 화면에서
 * 자동으로 돌리지 않는다.
 */
export default async function WorldPage({
  searchParams,
}: {
  searchParams: Promise<{ siteId?: string }>;
}) {
  const { siteId } = await searchParams;
  const sites = await fetchSites();

  if (!siteId) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          장비·작업자 상태는 현장 단위로 쌓입니다. 현장을 고르세요.
        </p>
        {sites.length === 0 ? (
          <EmptyState
            title="등록된 현장이 없습니다"
            action={{ label: "현장 등록", href: "/sites/new" }}
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {sites.map((site) => (
              <li key={site.siteId}>
                <Link
                  href={`/world?siteId=${encodeURIComponent(site.siteId)}`}
                  className="block rounded-lg border border-neutral-200 px-3 py-2 text-sm hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-900"
                >
                  <span className="font-medium">{site.name}</span>
                  <span className="ml-2 text-neutral-500">{site.siteId}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const { view, error } = await fetchStates(siteId);
  if (error) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState
          message={humanizeApiError(error.code, error.status, error.serverMessage)}
          detail={error.serverMessage}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <h2 className="text-sm font-semibold">{view.siteId}</h2>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          추적 중인 개체 {view.entityCount}건 (개체별 최신 관측)
        </p>
        <Link href="/world" className="mt-2 inline-block text-sm text-blue-600 hover:underline">
          다른 현장 선택
        </Link>
      </section>

      {view.entityCount === 0 ? (
        <EmptyState
          title="이 현장에 보고된 운동상태가 없습니다"
          description="장비·작업자 운동상태는 비행 중 Edge 장비가 보고합니다. 사람이 직접 입력하는 값이 아닙니다."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[42rem] text-left text-sm">
            <thead className="border-b border-neutral-200 text-xs uppercase text-neutral-500 dark:border-neutral-800">
              <tr>
                <th className="px-3 py-2">개체</th>
                <th className="px-3 py-2">종류</th>
                <th className="px-3 py-2">위치 (x, y, z)</th>
                <th className="px-3 py-2">위치 불확실성</th>
                <th className="px-3 py-2">속력</th>
                <th className="px-3 py-2">관측 시각</th>
              </tr>
            </thead>
            <tbody>
              {view.entities.map(({ state, positionUncertaintyM }) => (
                <tr
                  key={state.entityId}
                  className="border-b border-neutral-100 dark:border-neutral-900"
                >
                  <td className="px-3 py-2 font-medium">{state.entityId}</td>
                  <td className="px-3 py-2">{state.sourceClass}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {state.position.map((v) => v.toFixed(1)).join(", ")}
                  </td>
                  <td className="px-3 py-2">{formatUncertainty(positionUncertaintyM)}</td>
                  <td className="px-3 py-2">{speedOf(state.velocity).toFixed(2)} m/s</td>
                  <td className="px-3 py-2 text-neutral-600 dark:text-neutral-400">
                    {state.observedAt}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
