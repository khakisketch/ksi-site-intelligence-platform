import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { SITE_STATUS_LABEL, humanizeApiError } from "@/lib/core-api/labels";
import { listEquipmentStates } from "@/lib/core-api/phase34";
import { formatUncertainty } from "@/lib/core-api/phase34-labels";
import { listSitesCached } from "@/lib/core-api/cached";
import type { EquipmentStateListView, SiteView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatObservationAge, summarizeWorldFreshness } from "@/lib/world-status";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";

import { SitePlanView } from "./SitePlanView";

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
 * 평면도(SitePlanView)는 **site_frame 좌표를 그대로** 그린다 — 지리 배경을 깔려면
 * site_frame → WGS84 변환이 필요한데 그건 서버만 정확히 할 수 있고(어느 CRS 인지
 * 아는 쪽이 서버다) 아직 그 경로가 없다. 더 중요한 이유는 CPA/TTC 가 site_frame 에서
 * 계산된다는 것이다: 같은 공간에 그리면 그림이 숫자와 어긋날 수가 없다(그쪽 컴포넌트
 * docstring "왜 지리 지도가 아닌가").
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
        <div className="flex flex-col gap-1">
          <h2 className="text-[19px] font-bold tracking-tight break-keep">현장별 현황 보기</h2>
          <p className="text-sm break-keep text-ink-2">
            장비·작업자 상태는 현장 단위로 수신됩니다. 현장을 선택하면 가장 최근에 보고된
            관측만 표시하며, 관측이 없으면 그 사실을 그대로 표시합니다.
          </p>
        </div>
        {sites.length === 0 ? (
          <EmptyState
            title="등록된 현장이 없습니다"
            action={{ label: "현장 등록", href: "/sites/new" }}
          />
        ) : (
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {sites.map((site) => (
              <li key={site.siteId}>
                <Link
                  href={`/world?siteId=${encodeURIComponent(site.siteId)}`}
                  className="tap-target flex h-full flex-col gap-1 rounded-lg border border-line bg-surface p-3 text-sm transition-colors hover:bg-sunk"
                >
                  <span className="font-semibold break-keep">{site.name}</span>
                  <span className="num text-[11.5px] break-token text-ink-muted">{site.siteId}</span>
                  <span className="text-[12px] break-keep text-ink-2">
                    {SITE_STATUS_LABEL[site.status].label} · 최신 운동상태 보기
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const { view, error } = await fetchStates(siteId);
  const currentSite = sites.find((site) => site.siteId === siteId);
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

  const nowMs = new Date().getTime();
  const freshness = summarizeWorldFreshness(view.entities, nowMs);
  const uncertainties = view.entities.map((item) => item.positionUncertaintyM);
  const uncertaintyRange =
    uncertainties.length === 0
      ? null
      : {
          min: Math.min(...uncertainties),
          max: Math.max(...uncertainties),
        };

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <section className="rounded-lg border border-line p-4">
        <h2 className="text-sm font-semibold break-keep">{currentSite?.name ?? view.siteId}</h2>
        <p className="mt-1 text-sm text-ink-2">
          추적 중인 개체 {view.entityCount}건 (개체별 최신 관측)
        </p>
        <Link href="/world" className="tap-target mt-2 inline-flex items-center text-sm text-accent-text hover:underline">
          다른 현장 선택
        </Link>
      </section>

      <section aria-labelledby="world-layer-status" className="rounded-lg border border-line p-4">
        <h2 id="world-layer-status" className="text-sm font-semibold">
          데이터·레이어 상태
        </h2>
        <p className="mt-1 text-xs break-keep text-ink-muted">
          연결 상태를 추정하지 않고 실제 관측·Core 기록 시각과 현재 API 제공 범위만 표시합니다.
        </p>
        <dl className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-md bg-sunk p-3">
            <dt className="text-xs font-semibold text-ink-2">운동상태 레이어</dt>
            <dd className="mt-1 text-sm font-semibold">
              {freshness.latestObservedAt ? `${view.entityCount}개체 관측됨` : "관측 없음"}
            </dd>
            <dd className="mt-1 text-xs text-ink-muted">
              {freshness.latestObservedAt
                ? `최신 ${formatObservationAge(freshness.latestObservedAt, nowMs)} · ${formatKoreanDateTime(freshness.latestObservedAt)}`
                : "Edge가 보고한 운동상태가 없습니다."}
            </dd>
          </div>
          <div className="rounded-md bg-sunk p-3">
            <dt className="text-xs font-semibold text-ink-2">Core 수신</dt>
            <dd className="mt-1 text-sm font-semibold">
              {freshness.latestRecordedAt ? "원장 기록 있음" : "기록 없음"}
            </dd>
            <dd className="mt-1 text-xs text-ink-muted">
              {freshness.latestRecordedAt
                ? `최근 기록 ${formatKoreanDateTime(freshness.latestRecordedAt)} · 신고 장비 ${freshness.reportingDeviceCount}대`
                : "수신 시각과 신고 장비가 없습니다."}
            </dd>
          </div>
          <div className="rounded-md bg-sunk p-3">
            <dt className="text-xs font-semibold text-ink-2">위치 불확실성</dt>
            <dd className="mt-1 text-sm font-semibold">
              {uncertaintyRange
                ? `${formatUncertainty(uncertaintyRange.min)}–${formatUncertainty(uncertaintyRange.max)}`
                : "미산출"}
            </dd>
            <dd className="mt-1 text-xs text-ink-muted">
              공분산 기반 개체별 값 · 미래 관측 {freshness.clockSkewCount}건
            </dd>
          </div>
          <div className="rounded-md bg-sunk p-3">
            <dt className="text-xs font-semibold text-ink-2">공간 표현</dt>
            <dd className="mt-1 text-sm font-semibold">
              2D site frame {view.entityCount > 0 ? "표시 중" : "대기"}
            </dd>
            <dd className="mt-1 text-xs text-ink-muted">
              3D 모델 레이어 API 미연결 · 준비 중
            </dd>
          </div>
        </dl>
      </section>

      {view.entityCount === 0 ? (
        <EmptyState
          title="이 현장에 보고된 운동상태가 없습니다"
          description="장비·작업자 운동상태는 비행 중 Edge 장비가 보고합니다. 사람이 직접 입력하는 값이 아닙니다."
        />
      ) : (
        <>
          <SitePlanView entities={view.entities} />
          <div className="overflow-x-auto">
          <table className="w-full min-w-[42rem] text-left text-sm">
            <thead className="border-b border-line text-xs uppercase text-ink-muted">
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
              {view.entities.map(({ state, positionUncertaintyM, recordedAt, reportedBy }) => (
                <tr
                  key={state.entityId}
                  className="border-b border-line"
                >
                  <td className="px-3 py-2 font-medium">{state.entityId}</td>
                  <td className="px-3 py-2">{state.sourceClass}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {state.position.map((v) => v.toFixed(1)).join(", ")}
                  </td>
                  <td className="px-3 py-2">{formatUncertainty(positionUncertaintyM)}</td>
                  <td className="px-3 py-2">{speedOf(state.velocity).toFixed(2)} m/s</td>
                  <td className="px-3 py-2 text-ink-2">
                    <span className="block">{formatKoreanDateTime(state.observedAt)}</span>
                    <span className="block text-xs text-ink-muted">
                      {formatObservationAge(state.observedAt, nowMs)} · Core {formatKoreanDateTime(recordedAt)}
                      {reportedBy ? ` · ${reportedBy}` : " · 신고 장비 미상"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>
      )}
    </div>
  );
}
