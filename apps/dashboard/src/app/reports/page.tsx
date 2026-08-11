import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { listComparisonRequests } from "@/lib/core-api/comparison";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import {
  getChangeDetection,
  getProcessingJobArtifacts,
  getVolumeChanges,
} from "@/lib/core-api/phase34";
import { formatRatioPercent } from "@/lib/core-api/phase34-labels";
import type {
  ChangeDetectionView,
  ComparisonRequestContract,
  MissionRecordResponse,
  VolumeChangeListView,
} from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { OrthophotoOverlay } from "@/components/map/OrthophotoOverlay";
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
 * 그 임무의 비교 요청 전부(최신 먼저) — 두 가지 서로 다른 질문에 답한다.
 *
 * ① **결과가 아직 없을 때 왜 없는지**: "요청조차 안 됨"·"계산 중"·"실패함"은
 *    사용자에게 전혀 다른 사실인데 결과 유무만 보면 셋이 똑같이 빈 화면이다.
 *    이건 **최신** 요청이 답한다.
 * ② **지금 보이는 결과가 무슨 기준으로 계산됐는지**: 이건 최신 요청이 아니라
 *    **그 결과를 만든** 요청이 답한다(아래 `requestOf`).
 *
 * 조회 실패는 빈 배열로 다뤄 이 안내들만 비운다(결과 렌더를 가리지 않는다 —
 * fetchVolume 과 같은 원칙).
 */
async function fetchComparisonRequests(
  missionId: string,
): Promise<ComparisonRequestContract[]> {
  try {
    return (await listComparisonRequests(missionId)).requests;
  } catch {
    return [];
  }
}

/**
 * 결과를 만든 요청을 찾는다 — `changeDetectionId`/`volumeChangeId` 는 그 결과를
 * 만든 `requestId` 와 **같은 값**이다(비교 워커가 결정적으로 그렇게 붙인다,
 * `comparison_worker.run_comparison_request`).
 *
 * 예전에는 기준 패널이 늘 최신 요청을 읽었다. 한 임무에 비교를 두 번 하면
 * (예: 구역 없이 한 번, 구역을 확정해 한 번) 화면에 그려진 결과는 앞의 요청
 * 것인데 기준·계산범위는 뒤의 요청 것이 뜬다 — 서로 모순된 화면이 되고,
 * 그 모순은 화면 어디에도 표시되지 않는다.
 */
function requestOf(
  requests: readonly ComparisonRequestContract[],
  resultId: string | null | undefined,
): ComparisonRequestContract | null {
  if (!resultId) return null;
  return requests.find((request) => request.requestId === resultId) ?? null;
}

/**
 * 체적 리포트가 참조한 재구성 작업(epoch)에 정사영상(kind: "ortho")이
 * 등록돼 있으면 그 artifactId 를 돌려준다. 없으면(엔진이 만들지 않았거나
 * GSD 미지정으로 건너뛰었거나) null — 화면은 이 경우 정사영상 섹션을
 * 아예 그리지 않는다(`hasVolume` 과 같은 "없으면 안 그린다" 규약).
 */
async function fetchOrthophotoArtifactId(jobId: string): Promise<string | null> {
  try {
    const job = await getProcessingJobArtifacts(jobId);
    return job.artifacts.find((a) => a.kind === "ortho")?.artifactId ?? null;
  } catch {
    return null;
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
        <p className="text-sm break-keep text-ink-2">
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
                  className="block rounded-lg border border-line bg-surface px-3 py-2 text-sm transition-colors hover:bg-sunk"
                >
                  <span className="font-medium">{mission.missionId}</span>
                  <span className="ml-2 text-ink-muted">{mission.siteId}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const [{ view, error, notFound }, volume, requests] = await Promise.all([
    fetchChange(missionId),
    fetchVolume(missionId),
    fetchComparisonRequests(missionId),
  ]);
  // 최신 요청은 "결과가 왜 없는지"에만 쓴다 — 기준 패널은 아래에서 결과와
  // 짝지은 요청을 쓴다(requestOf docstring).
  const latestRequest = requests[0] ?? null;

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
  const orthophotoArtifactId = hasVolume
    ? await fetchOrthophotoArtifactId(volume.reports[0].report.current.jobId)
    : null;

  if (notFound && !hasVolume) {
    // "아직 계산되지 않음"의 이유를 가른다 — 요청 자체가 없는 것과, 요청은 있는데
    // 계산 중인 것과, 계산하다 실패한 것은 사용자에게 전혀 다른 사실이다.
    // ("계산했지만 변화가 없음"은 여기 오지 않는다 — 그때는 결과가 존재하므로
    //  아래 정상 렌더로 가고 후보 0건이 숫자로 보인다.)
    const status = latestRequest?.status ?? null;
    if (status === "QUEUED" || status === "RUNNING") {
      return (
        <div className="flex flex-col gap-4 p-4 sm:p-5">
          <EmptyState
            title="비교를 계산하는 중입니다"
            description={
              `${status === "QUEUED" ? "순서를 기다리는 중" : "계산 중"}입니다 — ` +
              "자료 크기에 따라 수 분 걸릴 수 있습니다. 잠시 후 새로고침하세요."
            }
            action={{ label: "임무 화면에서 진행 보기", href: `/missions/${encodeURIComponent(missionId)}` }}
          />
        </div>
      );
    }
    if (status === "FAILED") {
      return (
        <div className="flex flex-col gap-4 p-4 sm:p-5">
          <EmptyState
            title="비교에 실패했습니다"
            description={
              (latestRequest?.detail ?? "실패 사유가 기록되지 않았습니다.") +
              " 구역이나 시점을 바꿔 다시 요청할 수 있습니다."
            }
            action={{ label: "임무 화면에서 다시 요청", href: `/missions/${encodeURIComponent(missionId)}` }}
          />
        </div>
      );
    }
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <EmptyState
          title="이 임무의 리포트가 아직 없습니다"
          description="두 시점 비교가 아직 요청되지 않았습니다 — 임무 화면에서 비교할 두 재구성 결과를 골라 제출하세요."
          action={{ label: "임무 화면으로", href: `/missions/${encodeURIComponent(missionId)}` }}
        />
      </div>
    );
  }

  const latest = notFound ? null : view.latest;
  // 화면에 그려진 결과 각각을 만든 요청. 둘이 다른 요청일 수 있다(변화만 한 번,
  // 구역을 확정해 부피까지 한 번) — 그때는 각 값을 자기 출처에서 읽는다.
  const changeRequest = requestOf(requests, latest?.changeDetectionId);
  const volumeRequest = hasVolume
    ? requestOf(requests, volume.reports[0].report.volumeChangeId)
    : null;
  // 문턱·권고비율은 변화 탐지 쪽 개념이라 그 결과의 요청을 먼저 본다.
  const basisRequest = changeRequest ?? volumeRequest;
  // 재촬영 권고 CTA 가 어느 현장으로 보낼지 — 이 임무가 속한 site 를 이미 불러온
  // missions 목록에서 찾는다(별도 조회 없이 재사용, M2 폐루프).
  const currentMission = missions.find((mission) => mission.missionId === missionId) ?? null;
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <section className="rounded-lg border border-line bg-surface p-4">
        <h2 className="text-sm font-semibold break-keep text-ink-1">{missionId}</h2>
        {!notFound && (
          <p className="num mt-1 text-sm text-ink-2">
            변화 탐지 {view.resultCount}건 중 최신 · 계산 시각 {latest!.computedAt}
          </p>
        )}
        <Link
          href="/reports"
          className="mt-2 inline-block text-sm font-medium text-accent-text hover:underline"
        >
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
          {/* 권고가 켜졌을 때만 색이 붙는다 — 이 시스템에서 색은 안전 상태에만
              쓴다(globals.css "의미가 없는 곳에 색을 쓰지 않는다"). high 토큰을
              쓰는 이유도 같다: 원시 amber 를 직접 적으면 대비가 토큰 밖에서
              결정돼 한 곳에서 관리할 수 없다. */}
          <section
            className={`rounded-lg border p-4 ${
              view.revisitRecommended
                ? "border-high bg-high-bg"
                : "border-line bg-surface"
            }`}
          >
            <h3
              className={`text-sm font-semibold break-keep ${
                view.revisitRecommended ? "text-high-ink" : "text-ink-1"
              }`}
            >
              {view.revisitRecommended ? "추가 시점 수집 권고" : "추가 시점 수집 권고 없음"}
            </h3>
            <p
              className={`mt-1 text-sm break-keep ${
                view.revisitRecommended ? "text-high-ink" : "text-ink-2"
              }`}
            >
              변화 후보 비율 {formatRatioPercent(latest!.candidateRatio)} (기준{" "}
              {formatRatioPercent(view.revisitRatioThreshold)} 초과 시 권고)
            </p>
            {view.revisitRecommended && (
              <>
                <p className="mt-2 text-sm break-keep text-high-ink">
                  자동으로 재비행이 잡히지는 않습니다 — 원본 현장 AOI 로 SPATIAL_REFRESH
                  임무를 직접 발급하세요.
                </p>
                {currentMission && (
                  <Link
                    href={`/sites/${encodeURIComponent(currentMission.siteId)}/surveys/new?purpose=SPATIAL_REFRESH`}
                    className="tap-target mt-3 inline-block rounded-lg border border-high-ink bg-surface px-3 py-2 text-sm font-medium text-high-ink transition-colors hover:bg-high-bg"
                  >
                    SPATIAL_REFRESH 임무 초안 만들기
                  </Link>
                )}
              </>
            )}
          </section>

          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["비교 점 수", latest!.pointCount.toLocaleString()],
              ["변화 후보", latest!.candidateCount.toLocaleString()],
              ["거리 문턱", `${latest!.distanceThresholdM} m`],
              ["최대 거리", latest!.maxDistanceM === null ? "—" : `${latest!.maxDistanceM.toFixed(2)} m`],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-line bg-surface p-3">
                <dt className="text-xs break-keep text-ink-muted">{label}</dt>
                <dd className="num mt-1 text-lg font-semibold text-ink-1">{value}</dd>
              </div>
            ))}
          </dl>

          {latest!.candidateCount === 0 && (
            <p className="rounded-lg border border-line bg-surface p-4 text-sm break-keep text-ink-2">
              계산은 끝났고, <strong>움직인 것으로 볼 만한 지점이 없었습니다</strong> —
              비교 자체를 못 한 것이 아닙니다(점 {latest!.pointCount.toLocaleString()}개를
              모두 확인했고 기준({latest!.distanceThresholdM} m)을 넘는 것이 없었습니다).
            </p>
          )}

          <section className="rounded-lg border border-line bg-surface p-4 text-sm">
            <h3 className="font-semibold break-keep text-ink-1">비교 대상</h3>
            <p className="mt-1 font-mono text-xs break-token text-ink-2">
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

      {orthophotoArtifactId && (
        <OrthophotoOverlay
          jobId={volume!.reports[0].report.current.jobId}
          artifactId={orthophotoArtifactId}
        />
      )}

      {/* 이번 결과가 **무슨 기준으로** 계산됐는지 — 고정값이라고 숨기지 않는다
          (대표자 확정). 요청 생성 시점에 굳은 스냅샷이라, 시스템 기준이 나중에
          바뀌어도 이 결과는 여기 적힌 값으로 계산된 것이 맞다.
          출처는 **위에 그려진 결과를 만든 요청**이다(최신 요청이 아니다) —
          requestOf docstring 참조. */}
      {basisRequest && (
        <section className="rounded-lg border border-line bg-surface p-4 text-sm">
          <h3 className="font-semibold break-keep text-ink-1">이번 계산에 쓴 기준 (고정값)</h3>
          <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div>
              <dt className="text-xs break-keep text-ink-muted">움직임으로 칠 최소 거리</dt>
              <dd className="num mt-0.5 text-ink-1">
                {basisRequest.policy.distanceThresholdM} m
              </dd>
            </div>
            <div>
              <dt className="text-xs break-keep text-ink-muted">재촬영 권고 비율</dt>
              <dd className="num mt-0.5 text-ink-1">
                {(basisRequest.policy.revisitRatioThreshold * 100).toFixed(1)} %
              </dd>
            </div>
            <div>
              <dt className="text-xs break-keep text-ink-muted">기준 묶음</dt>
              <dd className="mt-0.5 font-mono text-xs break-token text-ink-1">
                {basisRequest.policy.policyVersion}
              </dd>
            </div>
          </dl>
          {/* 계산 범위(구역)는 부피 쪽 개념이라 **부피 결과를 만든 요청**에서
              읽는다 — 부피 결과가 없으면 이 줄은 그리지 않는다(구역을 확정하지
              않았다는 안내는 부피가 있을 때만 뜻이 있다). */}
          {volumeRequest && (
            <p className="mt-2 text-xs break-keep text-ink-muted">
              계산 범위:{" "}
              {volumeRequest.zones
                ? `사용자가 확정한 구역 ${Object.keys(volumeRequest.zones).length}개 (${volumeRequest.zoneCrs})`
                : "구역을 확정하지 않아 부피 비교는 하지 않았습니다"}
            </p>
          )}
          {/* 변화와 부피가 서로 다른 요청에서 나왔으면 그 사실을 감추지 않는다 —
              위 숫자는 변화 쪽 기준이고 계산 범위는 부피 쪽 것이다. */}
          {changeRequest && volumeRequest && changeRequest.requestId !== volumeRequest.requestId && (
            <p className="mt-2 text-xs break-keep text-ink-muted">
              변화와 부피는 서로 다른 요청에서 계산됐습니다 (변화 {changeRequest.requestId} ·
              부피 {volumeRequest.requestId}).
            </p>
          )}
        </section>
      )}
    </div>
  );
}
