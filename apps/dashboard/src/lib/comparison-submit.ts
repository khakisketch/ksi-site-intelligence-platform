import type {
  AoiVertex,
  ProcessingArtifactSummary,
  SiteProcessingJobSummary,
} from "@/lib/core-api/types";

/**
 * 두 시점 비교 제출 화면의 **순수 판정** — 렌더링과 분리해 테스트 가능하게 둔다.
 *
 * 이 파일에 서버 판정을 복제하지 않는다. 최종 가부는 Core 가 정하고
 * (`comparison_requests._resolve`), 여기 있는 것은 **제출 전에 사용자에게 미리
 * 알려주기 위한 안내**다 — 사용자가 눌러 보고 나서야 422 를 받는 대신, 왜 못
 * 고르는지를 목록에서 바로 보여주기 위한 것. 그래서 여기서 통과한 조합이
 * 서버에서 거부될 수는 있어도(레이스·원장 변화), 그 반대는 화면 결함이다.
 */

/** 재구성이 끝나 비교 후보가 될 수 있는 상태. */
const SUCCEEDED = "SUCCEEDED";

/** 비교 요청의 종료 상태 — 이 값이면 폴링을 멈춘다. */
const TERMINAL_COMPARISON_STATUSES = new Set(["SUCCEEDED", "FAILED"]);

export function isTerminalComparisonStatus(status: string): boolean {
  return TERMINAL_COMPARISON_STATUSES.has(status);
}

export interface ComparisonEpoch {
  jobId: string;
  missionId: string;
  issuedAt: string;
  /** 점군(point_cloud)이 등록돼 있는가 — 변화탐지의 입력. */
  hasPointCloud: boolean;
  /** 높이자료(dsm)가 등록돼 있는가 — 체적 비교의 입력. */
  hasDsm: boolean;
}

function hasKind(artifacts: readonly ProcessingArtifactSummary[], kind: string): boolean {
  return artifacts.some((a) => a.kind === kind);
}

/**
 * 비교 후보로 고를 수 있는 epoch 만 남긴다 — **성공한 재구성만**.
 *
 * 서버도 SUCCEEDED 가 아닌 작업을 거부하지만(`JOB_NOT_SUCCEEDED`), 진행 중인
 * 작업을 목록에 띄워 놓고 누른 뒤에 거부하는 것은 화면이 사용자를 막다른 길로
 * 보내는 것이다. 정렬은 서버가 이미 최신순으로 주지만(list_for_site) 화면이
 * 그 순서에 의존한다는 사실을 여기서 한 번 더 고정한다.
 */
export function selectableEpochs(
  jobs: readonly SiteProcessingJobSummary[],
): ComparisonEpoch[] {
  return jobs
    .filter((job) => job.status === SUCCEEDED)
    .map((job) => ({
      jobId: job.jobId,
      missionId: job.missionId,
      issuedAt: job.issuedAt,
      hasPointCloud: hasKind(job.artifacts, "point_cloud"),
      hasDsm: hasKind(job.artifacts, "dsm"),
    }))
    .sort((a, b) => b.issuedAt.localeCompare(a.issuedAt));
}

/**
 * "비교 시점(이후)" 후보를 **이 임무가 만든 재구성**으로 좁힌다.
 *
 * 서버(`comparison_requests._resolve`)는 currentJobId 가 요청 경로의 missionId
 * 소속이기를 요구한다(MISSION_MISMATCH) — baselineJobId 는 같은 현장이면 어느
 * 임무 소속이든 되지만, current 는 아니다: 비교 요청은 "이 임무가 만든 결과를
 * 과거와 견준다"는 지시로 그 임무 밑에 남는다. 화면이 이 비대칭을 모르고 site
 * 전체 목록을 두 드롭다운에 똑같이 띄우면, baseline/current 를 뒤집어 고른
 * 조합은 지도까지 다 채운 뒤(구역 확정 포함)에야 제출에서 거부된다 — 실
 * 인프라 재현에서 실제로 이렇게 막힌 사례(2026-08-10) 이후 추가.
 */
export function currentMissionEpochs(
  epochs: readonly ComparisonEpoch[],
  missionId: string,
): ComparisonEpoch[] {
  return epochs.filter((e) => e.missionId === missionId);
}

export interface ComparisonEligibility {
  /** 점군 변화탐지를 시도할 수 있는가(양쪽에 point_cloud 가 있어야 한다). */
  changeDetection: boolean;
  /** 체적 비교를 시도할 수 있는가(양쪽 dsm + 확정된 구역이 있어야 한다). */
  volumeChange: boolean;
  /** 둘 다 불가면 제출 자체가 거부된다(NOTHING_TO_COMPARE) — 그 사유. */
  blockedReason: string | null;
}

/**
 * 고른 두 epoch 로 무엇을 잴 수 있는지 — 제출 전 안내.
 *
 * `zonesConfirmed` 가 false 면 체적은 시도되지 않는다: 구역을 확정하지 않은 채
 * 제출하면 서버가 `zones=null` 로 받아 체적 비교를 건너뛴다. "확정 안 함"과
 * "구역이 없음"을 화면이 같은 말로 뭉뚱그리지 않기 위해 이 인자를 분리했다.
 */
export function comparisonEligibility(
  baseline: ComparisonEpoch | null,
  current: ComparisonEpoch | null,
  zonesConfirmed: boolean,
): ComparisonEligibility {
  if (baseline === null || current === null) {
    return {
      changeDetection: false,
      volumeChange: false,
      blockedReason: "비교할 두 시점을 모두 고르세요.",
    };
  }
  if (baseline.jobId === current.jobId) {
    return {
      changeDetection: false,
      volumeChange: false,
      blockedReason:
        "같은 결과끼리는 비교할 수 없습니다 — 변화가 0으로 나와 정상처럼 보이지만 " +
        "실제로는 아무것도 비교하지 않은 것입니다.",
    };
  }

  const changeDetection = baseline.hasPointCloud && current.hasPointCloud;
  const volumeChange = baseline.hasDsm && current.hasDsm && zonesConfirmed;

  if (!changeDetection && !volumeChange) {
    // 여기 오는 조합은 둘뿐이다. changeDetection 이 false 이므로 **점군은 반드시
    // 빠져 있고**(그게 곧 "양쪽에 점군이 있다"의 부정), 동시에 부피도 안 되려면
    // 높이자료가 없거나 구역이 확정되지 않아야 한다. 셋 중 하나만 어긋난
    // 경우(예: 점군만 없고 높이자료·구역은 멀쩡)는 부분 비교가 가능해 위에서
    // 이미 제출 가능으로 빠져나간다 — 그래서 갈래가 둘이다.
    //
    // 예전에는 여기 "한쪽에 높이자료가 없어 부피 비교를 할 수 없습니다" 갈래가
    // 있었는데 도달할 수 없었다(그 상황은 변화 비교가 되므로 제출 가능이다).
    const missingDsm = !baseline.hasDsm || !current.hasDsm;
    const reason = missingDsm
      ? "고른 두 결과에 비교할 자료가 없습니다(점군·높이자료 모두 없음)."
      : "점군이 없어 변화 비교를 할 수 없고, 구역을 확정하지 않아 부피 비교도 할 수 없습니다.";
    return { changeDetection: false, volumeChange: false, blockedReason: reason };
  }
  return { changeDetection, volumeChange, blockedReason: null };
}

/** 제출 가능한가 — 두 시점이 유효하고 잴 수 있는 것이 하나라도 있어야 한다. */
export function canSubmitComparison(eligibility: ComparisonEligibility): boolean {
  return eligibility.blockedReason === null;
}

/**
 * 지도에서 확정한 폴리곤을 서버가 받는 구역 형태로 옮긴다.
 *
 * **좌표 순서가 이 함수의 핵심이다.** 화면은 위도·경도(`AoiVertex`)로 다루고
 * GeoJSON 은 경도·위도 순이다 — 뒤집으면 구역이 지구 반대편으로 가고, 그러면
 * 서버는 "구역 안에 유효한 높이자료 셀이 없다"로 실패한다(실제로 그렇게
 * 실패하는 경로가 이미 있다). 링은 첫 점으로 닫는다(GeoJSON 요구사항).
 *
 * 정점이 3개 미만이면 폴리곤이 될 수 없으므로 `null` — 호출부는 이 경우
 * "구역 미확정"으로 다룬다(체적 비교를 건너뛴다).
 */
export function toZonePolygon(
  vertices: readonly AoiVertex[],
): Record<string, unknown> | null {
  if (vertices.length < 3) return null;
  const ring = vertices.map((v) => [v.lonDeg, v.latDeg]);
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push([first[0], first[1]]);
  return { type: "Polygon", coordinates: [ring] };
}

/** 서버가 받는 `zones` 한 벌 — 지금은 사용자가 구역 하나만 확정한다. */
export const COMPARISON_ZONE_ID = "comparison-zone";
export const COMPARISON_ZONE_CRS = "EPSG:4326";

export function toZonesPayload(
  vertices: readonly AoiVertex[],
): { zones: Record<string, Record<string, unknown>>; zoneCrs: string } | null {
  const polygon = toZonePolygon(vertices);
  if (polygon === null) return null;
  return { zones: { [COMPARISON_ZONE_ID]: polygon }, zoneCrs: COMPARISON_ZONE_CRS };
}
