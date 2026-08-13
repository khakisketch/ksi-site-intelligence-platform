import type {
  DesignConformanceEntry,
  DesignConformanceListView,
  DesignProgress,
  DesignProgressResponse,
  ProcessingJobArtifactsView,
} from "@/lib/core-api/types";

/**
 * 현장 보고서(M4-D) 데이터 조립 — **렌더에서 뗀 순수 함수**.
 *
 * `report/page.tsx` 는 세 번 조회한다(`getDesignProgress` → `getDesignConformance`
 * → `getProcessingJobArtifacts`). 이 파일은 그 세 응답을 **이미 받은 채로** 입력받아
 * "무엇을 보여줄 수 있는가"만 판정한다 — 네트워크를 이 파일 안에 두지 않는 이유는
 * `design-conformance.ts`/`comparison-submit.ts` 와 같다: 판정을 순수 함수로
 * 떼어야 vitest 가 서버 컴포넌트를 흉내 내지 않고도 이 로직을 검증할 수 있다.
 *
 * ## id-매칭 degrade 가 이 파일의 핵심이다
 *
 * `progress.latestDesignConformanceId` 가 가리키는 리포트를 `getDesignConformance`
 * 목록에서 **id 로 직접 찾는다** — 절대 0번째(가장 최근 것)를 그 리포트로
 * 가정하지 않는다. 목록은 그 리포트가 속한 임무(`latestMissionId`)의 전체
 * 이력이라 순서가 항상 "진척이 참조하는 리포트"와 같다는 보장이 없다(동시에 두
 * 번 계산을 요청했거나, 조회 사이에 새 리포트가 끼어들 수 있다). 못 찾으면
 * cut/fill/net 표만 생략하고, 구역 진척 표는 그대로 낸다 — 한쪽이 없다고 전체를
 * 감추지 않는다.
 */

/** cut/fill/net 리포트를 낼 수 없는 이유 — 화면이 사유별로 다른 문구를 낼 근거. */
export type ConformanceMatch =
  | { kind: "no-mission" }
  | { kind: "no-reports" }
  | { kind: "id-not-found" }
  | { kind: "matched"; entry: DesignConformanceEntry; totalNetM3: number | null };

/**
 * `latestDesignConformanceId` 를 그 임무의 설계 대비 잔량 목록에서 찾는다.
 *
 * `conformanceList` 는 호출부가 `latestMissionId` 로 이미 조회해 온 것이다(404 나
 * 조회 실패는 호출부가 `null` 로 접어 넘긴다 — `getVolumeChanges`/`fetchVolume` 과
 * 같은 규약). 이 함수는 그 결과를 받아 **찾기만** 한다.
 */
export function matchLatestConformanceReport(
  latestMissionId: string | null,
  latestDesignConformanceId: string,
  conformanceList: DesignConformanceListView | null,
): ConformanceMatch {
  if (latestMissionId === null) return { kind: "no-mission" };
  if (conformanceList === null) return { kind: "no-reports" };
  const entry = conformanceList.reports.find(
    (candidate) => candidate.report.designConformanceId === latestDesignConformanceId,
  );
  if (!entry) return { kind: "id-not-found" };
  return { kind: "matched", entry, totalNetM3: conformanceList.latestTotalNetM3 };
}

/**
 * 매칭된 리포트가 참조한 재구성 작업(epoch)에서 정사영상(kind: "ortho") 산출물을
 * 찾는다. `jobArtifacts` 가 없거나(조회 실패) ortho 가 없으면 `null` — 호출부는
 * 침묵 생략 대신 "정사영상 없음" 자리표시자를 보여준다(`fetchOrthophotoArtifactId`,
 * `src/app/reports/page.tsx` 와 같은 판정, 결과만 이 함수에서 순수화).
 */
export function resolveOrthophotoArtifactId(
  jobArtifacts: ProcessingJobArtifactsView | null,
): string | null {
  if (jobArtifacts === null) return null;
  return jobArtifacts.artifacts.find((artifact) => artifact.kind === "ortho")?.artifactId ?? null;
}

export interface SiteReportData {
  progress: DesignProgress | null;
  unmatchedZoneIds: string[];
  areaMismatchZoneIds: string[];
  /** `progress` 가 null 일 때 그 이유(`DesignProgressResponse.detail` 그대로). */
  detail: string | null;
  latestMissionId: string | null;
  /** `progress` 가 null 이면 애초에 매칭을 시도할 리포트 id 가 없다. */
  conformance: ConformanceMatch | { kind: "no-progress" };
  orthophotoArtifactId: string | null;
}

/**
 * 세 응답을 하나로 모은다 — `report/page.tsx` 가 렌더 직전에 부르는 마지막 조립.
 *
 * `conformanceList`/`jobArtifacts` 는 호출부가 앞선 두 조회로 이미 얻어 온 것을
 * 그대로 넘긴다(`jobArtifacts` 는 `matchLatestConformanceReport` 가 찾아 준
 * `entry.report.current.jobId` 로 조회한 결과라, 이 함수가 다시 계산하지 않고
 * 그 매칭을 여기서 한 번 더(같은 입력이므로 같은 결과) 계산해 최종 형태로 묶는다).
 */
export function collectSiteReportData(
  progressResponse: DesignProgressResponse,
  conformanceList: DesignConformanceListView | null,
  jobArtifacts: ProcessingJobArtifactsView | null,
): SiteReportData {
  const { progress, unmatchedZoneIds, areaMismatchZoneIds, detail, latestMissionId } =
    progressResponse;

  if (progress === null) {
    return {
      progress: null,
      unmatchedZoneIds,
      areaMismatchZoneIds,
      detail,
      latestMissionId,
      conformance: { kind: "no-progress" },
      orthophotoArtifactId: null,
    };
  }

  const conformance = matchLatestConformanceReport(
    latestMissionId,
    progress.latestDesignConformanceId,
    conformanceList,
  );
  const orthophotoArtifactId =
    conformance.kind === "matched" ? resolveOrthophotoArtifactId(jobArtifacts) : null;

  return {
    progress,
    unmatchedZoneIds,
    areaMismatchZoneIds,
    detail,
    latestMissionId,
    conformance,
    orthophotoArtifactId,
  };
}
