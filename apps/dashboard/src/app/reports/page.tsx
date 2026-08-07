import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import { getChangeDetection, getVolumeChanges } from "@/lib/core-api/phase34";
import { formatRatioPercent } from "@/lib/core-api/phase34-labels";
import type {
  ChangeDetectionView,
  MissionRecordResponse,
  VolumeChangeListView,
} from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { VolumeChangeSummary } from "@/components/reports/VolumeChangeSummary";

type Result =
  | { view: ChangeDetectionView; error: null; notFound: false }
  | { view: null; error: null; notFound: true }
  | { view: null; error: CoreApiError; notFound: false };

async function fetchChange(missionId: string): Promise<Result> {
  try {
    return { view: await getChangeDetection(missionId), error: null, notFound: false };
  } catch (error) {
    if (error instanceof CoreApiError) {
      // 404 는 "이 임무의 변화 탐지가 아직 없다" — 오류가 아니라 빈 상태다.
      if (error.status === 404) return { view: null, error: null, notFound: true };
      return { view: null, error, notFound: false };
    }
    throw error;
  }
}

/**
 * 체적 리포트는 변화 탐지와 **독립적으로** 없을 수 있다 — DSM 두 시점이 아직
 * 없으면 여기만 비고, 그렇다고 화면 전체를 오류로 만들지 않는다. 404 는 빈
 * 상태이고, 그 외 오류도 이 섹션만 비운다(주 내용인 변화 탐지를 가리지 않는다).
 */
async function fetchVolume(missionId: string): Promise<VolumeChangeListView | null> {
  try {
    return await getVolumeChanges(missionId);
  } catch {
    return null;
  }
}

async function fetchMissions(): Promise<MissionRecordResponse[]> {
  try {
    return await listMissions();
  } catch {
    return [];
  }
}

/**
 * 보고서 — Phase 4 시계열 변화 탐지 + 재방문 권고 (PRD §15.4, §15.2 ⑤).
 *
 * `revisitRecommended` 는 **권고**다. 자동으로 재비행을 만들지 않는다 — 운영자가
 * 이 신호를 보고 원본 site AOI 로 SPATIAL_REFRESH 임무를 발급한다(Coverage
 * Recovery 의 `recoveryRecommended` 와 같은 관계).
 *
 * 권고와 함께 **그 권고가 켜진 기준값**(`revisitRatioThreshold`)을 반드시 같이
 * 보여준다 — 불리언만 보면 운영자는 그 신호를 신뢰할 근거가 없다.
 */
export default async function ReportsPage({
  searchParams,
}: {
  searchParams: Promise<{ missionId?: string }>;
}) {
  const { missionId } = await searchParams;
  const missions = await fetchMissions();

  if (!missionId) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          변화 탐지 결과는 임무 단위로 쌓입니다. 확인할 임무를 고르세요.
        </p>
        {missions.length === 0 ? (
          <EmptyState
            title="발급된 임무가 없습니다"
            action={{ label: "임무 목록", href: "/missions" }}
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {missions.map((mission) => (
              <li key={mission.missionId}>
                <Link
                  href={`/reports?missionId=${encodeURIComponent(mission.missionId)}`}
                  className="block rounded-lg border border-neutral-200 px-3 py-2 text-sm hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-900"
                >
                  <span className="font-medium">{mission.missionId}</span>
                  <span className="ml-2 text-neutral-500">{mission.siteId}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const [{ view, error, notFound }, volume] = await Promise.all([
    fetchChange(missionId),
    fetchVolume(missionId),
  ]);

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

  // 변화 탐지(point cloud C2C)와 체적(DSM diff)은 서로 다른 입력에서 나오는
  // 독립된 리포트다 — 한쪽만 있는 것이 정상 상태다. 예전에는 notFound 분기가
  // 함수 전체를 조기 반환해 체적 섹션 코드까지 아예 도달하지 못했다(실제
  // 브라우저 렌더 확인에서 드러난 결함 — vitest/tsc 는 이 조합을 못 잡는다).
  // 이제 두 데이터의 유무를 독립적으로 판단해 있는 것만 그린다.
  const hasVolume = volume !== null && volume.reports.length > 0;

  if (notFound && !hasVolume) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <EmptyState
          title="이 임무의 리포트가 아직 없습니다"
          description="두 시점을 비교한 변화 탐지·체적 결과가 아직 보고되지 않았습니다."
          action={{ label: "다른 임무 선택", href: "/reports" }}
        />
      </div>
    );
  }

  const latest = notFound ? null : view.latest;
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <h2 className="text-sm font-semibold">{missionId}</h2>
        {!notFound && (
          <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            변화 탐지 {view.resultCount}건 중 최신 · 계산 시각 {latest!.computedAt}
          </p>
        )}
        <Link href="/reports" className="mt-2 inline-block text-sm text-blue-600 hover:underline">
          다른 임무 선택
        </Link>
      </section>

      {notFound ? (
        <EmptyState
          title="변화 탐지 결과가 없습니다"
          description="두 시점의 point cloud 를 비교한 결과가 아직 보고되지 않았습니다."
        />
      ) : (
        <>
          <section
            className={`rounded-lg border p-4 ${
              view.revisitRecommended
                ? "border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950"
                : "border-neutral-200 dark:border-neutral-800"
            }`}
          >
            <h3 className="text-sm font-semibold">
              {view.revisitRecommended ? "추가 시점 수집 권고" : "추가 시점 수집 권고 없음"}
            </h3>
            <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">
              변화 후보 비율 {formatRatioPercent(latest!.candidateRatio)} (기준{" "}
              {formatRatioPercent(view.revisitRatioThreshold)} 초과 시 권고)
            </p>
            {view.revisitRecommended && (
              <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
                자동으로 재비행이 잡히지는 않습니다 — 원본 현장 AOI 로 SPATIAL_REFRESH
                임무를 직접 발급하세요.
              </p>
            )}
          </section>

          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["비교 점 수", latest!.pointCount.toLocaleString()],
              ["변화 후보", latest!.candidateCount.toLocaleString()],
              ["거리 문턱", `${latest!.distanceThresholdM} m`],
              ["최대 거리", latest!.maxDistanceM === null ? "—" : `${latest!.maxDistanceM.toFixed(2)} m`],
            ].map(([label, value]) => (
              <div
                key={label}
                className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
              >
                <dt className="text-xs text-neutral-500">{label}</dt>
                <dd className="mt-1 text-lg font-semibold">{value}</dd>
              </div>
            ))}
          </dl>

          <section className="rounded-lg border border-neutral-200 p-4 text-sm dark:border-neutral-800">
            <h3 className="font-semibold">비교 대상</h3>
            <p className="mt-1 font-mono text-xs text-neutral-600 dark:text-neutral-400">
              baseline: {latest!.baseline.jobId} / {latest!.baseline.artifactId}
              <br />
              current: {latest!.current.jobId} / {latest!.current.artifactId}
            </p>
          </section>
        </>
      )}

      {hasVolume && (
        <VolumeChangeSummary
          entry={volume.reports[0]}
          totalNetM3={volume.latestTotalNetM3}
        />
      )}
    </div>
  );
}
