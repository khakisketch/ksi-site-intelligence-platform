import "server-only";

import type { AnalysisListItem } from "@/lib/core-api/analysis";
import type { SpatialAssetCatalogItem, SpatialAssetCatalogPage } from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";
import type {
  WorkspaceAnalysisRef,
  WorkspaceObservationFact,
  WorkspaceServerFacts,
} from "@/lib/site-workspace-entry";
import { parseCalendarDate } from "@/lib/site-workspace-entry";

/**
 * SWX-1 서버 어댑터 — `site-workspace-entry.ts`가 먹는 사실 묶음을 기존 Core
 * 목록에서 옮기는 유일한 자리.
 *
 * TODO(SWX-1 Core projection — 다른 작업자가 병렬 구축 중): 아래 전이적
 * 옮김을 권위 프로젝션으로 교체한다. 필요한 Core 경로·형태:
 *   `GET /v1/sites/{siteId}/workspace-view`
 * 응답(형태는 Core 소유·미확정, 이 파일이 지어내지 않는다)에 반드시 있어야
 * 할 최소 항목 —
 *   (1) `defaultObservation` (일반 진입용 서버 지정 기본 관측: observationEpochId,
 *       workAreaId, assetRef, 서버 선언 viewAvailable),
 *   (2) 구역별 관측 후보 목록(관측 식별·포착 정밀도·버전·서버 선언 표시 가용성),
 *   (3) 페이지·supersession·읽기 불가 신규 버전을 가리는 최신/가용성 판정,
 *   (4) 포착 정밀도 필드: EXACT_INTERVAL은 `declared.captureStartedAt` +
 *       `declared.captureEndedAt`(둘 다 ISO 시각), DATE_ONLY는
 *       `declared.captureDate`(`YYYY-MM-DD` 달력 날짜, 시각 없음), 둘 다
 *       없으면 UNKNOWN.
 * 그 전까지 `serverDefault`는 null이며, 일반 진입은 목록 정렬로 "최신"을
 * 대신 고르지 않고 호출자의 명시적 전이 선택을 쓴다. `viewAvailable` 전이
 * 옮김(검사 래스터 유무)은 표시용 발자국 가용성일 뿐, 정량 적합·최신 판정이
 * 아니다.
 */

/**
 * Core `declared.captureDate`(DATE_ONLY, `YYYY-MM-DD`)의 유일한 읽기 자리.
 *
 * - 카탈로그 항목에 `captureDate`가 있으면(부가적 Core 변경 진행 중) 검증 뒤
 *   그대로 쓴다. 없으면(기존 기록) null — submittedAt/observedAt/등록 시각에서
 *   날짜를 유도하지 않는다.
 * - `captureStartedAt`/`captureEndedAt`가 있으면 구간이 우선한다(정밀도 판정은
 *   `observationPrecisionOf`가 맡는다).
 */
function readCaptureDate(declared: SpatialAssetCatalogItem["declared"]): string | null {
  // 부가적 Core 변경(카탈로그 항목의 `captureDate`)이 오기 전에는 이 키가 없어
  // null이다. unknown 캐스트는 그 부가 키를 읽는 유일한 자리다.
  const candidate = (declared as { captureDate?: unknown }).captureDate ?? null;
  return parseCalendarDate(candidate);
}

export function toWorkspaceObservationFacts(
  page: SpatialAssetCatalogPage | null,
): WorkspaceObservationFact[] {
  if (!page) return [];
  return page.assets.map((item) => ({
    observationEpochId: item.observationEpochId,
    workAreaId: item.workAreaId,
    assetRef: item.assetRef,
    kind: item.kind,
    revision: item.revision,
    captureStartedAt: item.declared.captureStartedAt,
    captureEndedAt: item.declared.captureEndedAt,
    captureDate: readCaptureDate(item.declared),
    // 전이적 옮김: 검사된 래스터 사실이 있을 때만 발자국 표시가 가능하다.
    // 정량 사용 가능·최신 여부가 아니다.
    viewAvailable: item.inspection?.raster != null,
  }));
}

export function toWorkspaceAnalysisRefs(
  items: readonly AnalysisListItem[] | null,
  selectorsById: ReadonlyMap<string, { baseline: WorkspaceAnalysisRef["baseline"]; current: WorkspaceAnalysisRef["current"] }> = new Map(),
): WorkspaceAnalysisRef[] {
  if (!items) return [];
  const out: WorkspaceAnalysisRef[] = [];
  for (const item of items) {
    const selectors = selectorsById.get(item.analysisId);
    // 목록 항목에는 baseline/current 선택자가 없으므로, 상세 없이는 결과
    // 링크 복원에 쓰지 않는다 — 있는 그대로 두되 선택자는 비워 두지 않고
    // 아예 제외한다(없는 selector를 지어내지 않는다).
    if (!selectors) continue;
    out.push({
      analysisId: item.analysisId,
      workAreaId: item.workAreaId,
      baseline: selectors.baseline,
      current: selectors.current,
    });
  }
  return out;
}

export function buildWorkspaceServerFacts({
  siteId,
  areas,
  assetsPage,
  analyses,
}: {
  siteId: string;
  areas: readonly WorkArea[];
  assetsPage: SpatialAssetCatalogPage | null;
  analyses: readonly AnalysisListItem[] | null;
}): WorkspaceServerFacts {
  return {
    siteId,
    authorizedWorkAreaIds: areas.filter((area) => area.status === "ACTIVE").map((area) => area.workAreaId),
    // 권위 프로젝션 착륙 전 — null. 호출자가 전이 선택을 명시적으로 맡는다.
    serverDefault: null,
    observations: toWorkspaceObservationFacts(assetsPage),
    analyses: toWorkspaceAnalysisRefs(analyses),
  };
}
