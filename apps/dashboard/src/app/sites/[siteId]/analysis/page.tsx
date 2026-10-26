import Link from "next/link";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { getAnalysis, listAnalyses, listAnalysisObservations } from "@/lib/core-api/analysis";
import { getSpatialAsset, type SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";

import { AnalysisStartGuide } from "./AnalysisStartGuide";
import { resolveAnalysisCurrentHint, resolveAnalysisScope, resolveExactAnalysisSelectorHints, parseVisualBrowsingContext, visualBrowsingReturnHref } from "@/lib/operator-journey";
import { AnalysisRequestPanel, type CatalogInspectPair } from "./AnalysisRequestPanel";
import { parseScopeId } from "../site-spatial";

export const metadata = { title: "현장 변화 분석 · KSI" };

export default async function SiteAnalysisPage({ params, searchParams }: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ analysisId?: string | string[]; workAreaId?: string | string[]; currentWorkOrderId?: string | string[]; assetRef?: string | string[]; visualAAssetRef?: string | string[]; visualBAssetRef?: string | string[]; hintBaselineWorkOrderId?: string | string[]; hintBaselineSubmissionRef?: string | string[]; hintBaselineRevision?: string | string[]; hintCurrentWorkOrderId?: string | string[]; hintCurrentSubmissionRef?: string | string[]; hintCurrentRevision?: string | string[] }>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const single = (value: string | string[] | undefined): string | undefined =>
    Array.isArray(value) ? value[0] : value;
  const analysisId = single(query.analysisId);
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={`/sites/${encodeURIComponent(siteId)}/analysis`} />;
  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    // A Site 404 is the only response that establishes this route as unavailable.
    // Child analysis routes can be absent in a local graph while the Site itself
    // remains readable; resolve the scoped Site before asking for those children.
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="현장 접근을 확인하지 못했습니다." retryable /></div>;
  }

  let loaded: {
    areas: Awaited<ReturnType<typeof listWorkAreas>>;
    observations: Awaited<ReturnType<typeof listAnalysisObservations>>;
    attributedObservations: (Awaited<ReturnType<typeof listAnalysisObservations>>[number] & { workAreaIds: string[] })[];
    unattributedObservationCount: number;
    workOrderNames: Record<string, string>;
    analyses: Awaited<ReturnType<typeof listAnalyses>>;
    selectedDetail: Awaited<ReturnType<typeof getAnalysis>> | null;
  } | null = null;
  let childError: unknown;
  let childStage: "lists" | "detail" = "lists";
  try {
    const [areas, observations, listedAnalyses, workOrders] = await Promise.all([
      listWorkAreas(siteId),
      listAnalysisObservations(siteId),
      listAnalyses(siteId, { limit: 50 }),
      listObservationWorkOrders(siteId).catch(() => null),
    ]);
    let detail: Awaited<ReturnType<typeof getAnalysis>> | null = null;
    if (analysisId && !listedAnalyses.items.some((item) => item.analysisId === analysisId)) {
      childStage = "detail";
      detail = await getAnalysis(siteId, analysisId);
    }
    const workAreasByOrder = new Map<string, string[]>();
    const workOrderNames: Record<string, string> = {};
    for (const order of workOrders ?? []) {
      if (order.siteId !== siteId || order.organizationId !== session.principal.organizationId) continue;
      if (typeof order.name === "string" && order.name.trim().length > 0) {
        workOrderNames[order.workOrderId] = order.name;
      }
      const workAreaIds = Array.isArray(order.workAreaIds)
        ? [...new Set(order.workAreaIds.filter((id): id is string => typeof id === "string" && id.length > 0))]
        : [];
      if (workAreaIds.length > 0) workAreasByOrder.set(order.workOrderId, workAreaIds);
    }
    let unattributedObservationCount = 0;
    const attributedObservations = observations.flatMap((observation) => {
      const workAreaIds = workAreasByOrder.get(observation.selector.workOrderId);
      if (!workAreaIds) {
        unattributedObservationCount += 1;
        return [];
      }
      return [{ ...observation, workAreaIds }];
    });
    loaded = { areas, observations, attributedObservations, unattributedObservationCount, workOrderNames, analyses: listedAnalyses, selectedDetail: detail };
  } catch (error) {
    childError = error;
  }
  const unavailable = childStage === "lists" && childError instanceof CoreApiError && childError.status === 404;
  const missingDetail = childStage === "detail" && childError instanceof CoreApiError && childError.status === 404;
  const denied = childError instanceof CoreApiError && childError.status === 403;
  const retryAfterSeconds = childError instanceof CoreApiError ? childError.retryAfterSeconds : undefined;
  const canCreate = session.principal.permissions.includes("SITES_WRITE");
  const hasDeepLink = typeof analysisId === "string" && analysisId.length > 0;
  const journeyScope = loaded
    ? resolveAnalysisScope({
        areas: loaded.areas.workAreas.map((area) => ({ workAreaId: area.workAreaId, name: area.name, status: area.status })),
        rawWorkAreaId: single(query.workAreaId),
        hasPendingAttempt: false,
        hasAnalysisDeepLink: hasDeepLink,
      })
    : { initialWorkAreaId: "", scopeNotice: null, invalidRequested: false };
  const deeplinkArea = loaded?.selectedDetail?.workAreaId
    ?? (hasDeepLink ? loaded?.analyses.items.find((item) => item.analysisId === analysisId)?.workAreaId ?? "" : "");
  const effectiveWorkAreaId = hasDeepLink ? (deeplinkArea ?? "") : journeyScope.initialWorkAreaId;
  // 정확한 선택자 인계 힌트 — 키가 하나라도 있으면 정확 모드다. 원문 값을
  // 그대로 넘기며(반복 배열을 첫 값으로 접지 않는다), 일부만 있거나 배열이면
  // invalid 경로로 둔다. 정확 모드가 켜지면 WorkOrder 근사로 돌아가지 않는다.
  const hintKeys = [
    query.hintBaselineWorkOrderId, query.hintBaselineSubmissionRef, query.hintBaselineRevision,
    query.hintCurrentWorkOrderId, query.hintCurrentSubmissionRef, query.hintCurrentRevision,
  ] as const;
  const hintModeSupplied = hintKeys.some((value) => value !== undefined);
  const exactHint = loaded
    ? resolveExactAnalysisSelectorHints({
        candidates: loaded.attributedObservations,
        workAreaId: effectiveWorkAreaId,
        rawBaseline: hintKeys[0] !== undefined || hintKeys[1] !== undefined || hintKeys[2] !== undefined
          ? {
              workOrderId: query.hintBaselineWorkOrderId,
              submissionRef: query.hintBaselineSubmissionRef,
              revision: query.hintBaselineRevision,
            }
          : undefined,
        rawCurrent: hintKeys[3] !== undefined || hintKeys[4] !== undefined || hintKeys[5] !== undefined
          ? {
              workOrderId: query.hintCurrentWorkOrderId,
              submissionRef: query.hintCurrentSubmissionRef,
              revision: query.hintCurrentRevision,
            }
          : undefined,
        hasPendingAttempt: false,
        hasAnalysisDeepLink: hasDeepLink,
      })
    : { baseline: null, current: null, notice: null };
  const currentHint = loaded && !hintModeSupplied
    ? resolveAnalysisCurrentHint({
        candidates: loaded.attributedObservations,
        workAreaId: effectiveWorkAreaId,
        rawCurrentWorkOrderId: query.currentWorkOrderId,
        hasPendingAttempt: false,
        hasAnalysisDeepLink: hasDeepLink,
      })
    : { currentWorkOrderId: null, notice: null };
  // 후보와 맞지 않은 인계 선택자도 화면에 그대로 보인다 — 미리 고를 수는
  // 없지만, 가져온 쌍이 무엇이었는지와 왜 고르지 않았는지를 밝힌다.
  // 형태 검증만 하며(정확도·적합성 판정 없음), 후보 목록과 대조하지 않는다.
  const parseDisplayHint = (value: {
    workOrderId: string | string[] | undefined;
    submissionRef: string | string[] | undefined;
    revision: string | string[] | undefined;
  }): { workOrderId: string; submissionRef: string; revision: number } | null => {
    if (typeof value.workOrderId !== "string" || value.workOrderId.trim().length === 0) return null;
    if (typeof value.submissionRef !== "string" || !/^ers-v1-[0-9a-f]{64}$/.test(value.submissionRef)) return null;
    const revision = typeof value.revision === "string" && /^\d+$/.test(value.revision.trim()) ? Number(value.revision.trim()) : value.revision;
    if (typeof revision !== "number" || !Number.isSafeInteger(revision) || revision <= 0) return null;
    return { workOrderId: value.workOrderId, submissionRef: value.submissionRef, revision };
  };
  const rawDisplayBaseline = hintModeSupplied
    ? parseDisplayHint({ workOrderId: query.hintBaselineWorkOrderId, submissionRef: query.hintBaselineSubmissionRef, revision: query.hintBaselineRevision })
    : null;
  const rawDisplayCurrent = hintModeSupplied
    ? parseDisplayHint({ workOrderId: query.hintCurrentWorkOrderId, submissionRef: query.hintCurrentSubmissionRef, revision: query.hintCurrentRevision })
    : null;
  // 후보와 정확히 맞은 선택자는 폼이 미리 고른다. 맞지 않은 유효 형태의
  // 선택자는 표시용으로만 넘긴다(요청 입력이 아님).
  const broughtSelectors = rawDisplayBaseline || rawDisplayCurrent
    ? {
      baseline: exactHint.baseline ?? rawDisplayBaseline,
      baselineMatched: exactHint.baseline !== null,
      current: exactHint.current ?? rawDisplayCurrent,
      currentMatched: exactHint.current !== null,
    }
    : null;
  // 탐색 복귀 맥락 — 모양만 본 뒤, 같은 구역의 카탈로그와 한 번만 대조한다
  // (메타데이터 1회 읽기, 바이트 없음). 묶이지 않은 참조는 버리고 사유를 둔다.
  const visualShape = parseVisualBrowsingContext({
    workAreaId: query.workAreaId ?? effectiveWorkAreaId,
    visualAAssetRef: query.visualAAssetRef,
    visualBAssetRef: query.visualBAssetRef,
  });
  let visualContext = visualShape && effectiveWorkAreaId && visualShape.workAreaId === effectiveWorkAreaId
    ? visualShape
    : null;
  const visualSupplied = query.visualAAssetRef !== undefined || query.visualBAssetRef !== undefined;
  let visualContextNotice: string | null = visualSupplied && !visualContext
    ? "요청한 탐색 맥락을 확인하지 못했습니다. 작업구역을 직접 선택하세요."
    : null;
  // 바인딩된 시각 쌍의 카탈로그 해석(읽기 전용 조건 확인용). 후보 가입과
  // 무관한 서버 사실이며, 묶이지 않은 참조는 싣지 않는다.
  let catalogPair: CatalogInspectPair | null = null;
  if (visualContext && effectiveWorkAreaId) {
    // 바인딩된 시각 쌍의 카탈로그 해석 — 같은 구역의 정확한 자료 조회를
    // 참조별로 최대 2건 병렬로 읽는다. 목록 페이징과 무관하므로 페이지 밖
    // 유효 참조도 놓치지 않는다. 반환된 사실의 현장·구역·참조 일치를
    // 확인한 뒤에만 싣는다(외부·모순 참조는 불투명). 실패·거부·모름은
    // 빈 맥락으로 닫는다.
    const areaId = effectiveWorkAreaId;
    const [itemA, itemB] = await Promise.all([
      getSpatialAsset(siteId, areaId, visualContext.visualAAssetRef).catch(() => null),
      getSpatialAsset(siteId, areaId, visualContext.visualBAssetRef).catch(() => null),
    ]);
    const boundItem = (item: SpatialAssetCatalogItem | null, assetRef: string) =>
      item !== null && item.siteId === siteId && item.workAreaId === areaId && item.assetRef === assetRef
        ? item
        : null;
    const resolvedA = boundItem(itemA, visualContext.visualAAssetRef);
    const resolvedB = boundItem(itemB, visualContext.visualBAssetRef);
    if (!resolvedA || !resolvedB) {
      visualContext = null;
      visualContextNotice = "요청한 탐색 맥락의 자료를 이 구역에서 확인하지 못했습니다. 기준·현재 관측을 직접 선택하세요.";
    } else {
      // 시각 쌍의 카탈로그 해석 — 같은 구역에서 바인딩된 두 자료를 서버
      // 사실(선택자 삼중항·선언·검사)에서 푼다. 원문 쿼리·후보 가입 여부와
      // 무관하며, 읽기 전용 조건 확인에만 쓴다(실행 입력이 아니다).
      const toInspectSide = (item: SpatialAssetCatalogItem) => ({
        assetRef: item.assetRef,
        selector: { workOrderId: item.workOrderId, submissionRef: item.submissionRef, revision: item.revision },
        kind: item.kind,
        captureStartedAt: item.declared.captureStartedAt,
        captureEndedAt: item.declared.captureEndedAt,
        captureDate: item.declared.captureDate ?? null,
        revision: item.revision,
        declaredFileName: item.declared.fileName,
        verticalIdentifier: item.inspection.raster?.observedVerticalReference?.identifier ?? null,
        verticalBasis: item.inspection.raster?.observedVerticalReference?.basis ?? null,
        inspectionOutcome: item.inspection.outcome,
      });
      catalogPair = { workAreaId: areaId, a: toInspectSide(resolvedA), b: toInspectSide(resolvedB) };
    }
  }
  const visualReturnHref = visualContext && effectiveWorkAreaId
    ? visualBrowsingReturnHref(`/sites/${encodeURIComponent(siteId)}`, visualContext, effectiveWorkAreaId)
    : null;
  // 목록을 읽지 못해 검증된 범위가 없을 때는 사용자가 가져온 쿼리를 그대로 믿지
  // 않고 다듬은 값만 복귀 링크에 싣는다. 목적지(등록 자료)가 범위를 다시 검증해
  // 닫히므로(모르는 구역은 실패 공지), 여기서 자료 유효성을 단정하지 않는다.
  // 배열 쿼리는 단일 선택이 아니므로 싣지 않는다.
  const rawWorkAreaId = typeof query.workAreaId === "string" ? query.workAreaId : undefined;
  const fallbackScope = loaded ? effectiveWorkAreaId : (parseScopeId(rawWorkAreaId) ?? "");
  // 탐색에서 들고 온 관측 참조는 헤더 복귀용으로만 둔다. 분석 선택
  // (analysisId·currentWorkOrderId)과 frozen 결과 입력은 이 값을 읽지 않는다.
  // 현황으로 돌아가면 탐색 진입이 카탈로그와 재대조해 모르는 참조를 공지만 둔다.
  const headerAssetRef = effectiveWorkAreaId
    ? parseScopeId(typeof query.assetRef === "string" ? query.assetRef : undefined)
    : null;
  return <>
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab="results"
      canCreateWorkOrder={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
      canEditAoi={canCreate}
      scopedWorkAreaId={effectiveWorkAreaId || null}
      scopedAssetRef={headerAssetRef}
      visualContext={visualContext && visualContext.workAreaId === effectiveWorkAreaId ? visualContext : null}
    />
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-end justify-between gap-2 border-b border-line pb-2.5">
        <div>
          <h2 className="mt-1 text-[24px] font-bold tracking-[-0.03em] sm:text-[26px]">현장 변화 분석</h2>
          <p className="mt-1 max-w-2xl text-[13px] leading-6 text-ink-2">기준 자료와 비교할 자료를 고르고 변화량과 근거를 살펴보세요.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          {loaded && (loaded.analyses.items.length > 0 || loaded.analyses.nextCursor) && (
            <p aria-label="분석 요약" className="rounded-lg border border-line bg-sunk/40 px-3 py-1.5 text-[12px] text-ink-2">
              <span className="font-semibold text-ink-1">분석 기록 {loaded.analyses.items.length}{loaded.analyses.nextCursor ? "+" : ""}건</span>
              <span aria-hidden="true" className="mx-1.5 text-line-strong">·</span>
              <span>작업구역 {loaded.areas.workAreas.length}개</span>
              <span aria-hidden="true" className="mx-1.5 text-line-strong">·</span>
              <span>관측 자료 {loaded.attributedObservations.length}건</span>
            </p>
          )}
          <Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="tap-target inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline">외부 비교 기록</Link>
        </div>
      </header>
      {loaded ? <>
        {/* 기록이 있으면 결과 요약·이력이 먼저 보인다. 기록이 없으면 실제
            선택 폼이 먼저 오고, 시작 안내는 접힌 도움말로 뒤에 둔다. */}
        <AnalysisRequestPanel
          siteId={siteId}
          organizationId={session.principal.organizationId}
          principalId={session.principal.principalId}
          workAreas={loaded.areas.workAreas}
          observations={loaded.attributedObservations}
          siteObservations={loaded.observations}
          unattributedObservationCount={loaded.unattributedObservationCount}
          workOrderNames={loaded.workOrderNames}
          initialPage={loaded.analyses}
          initialSelectedDetail={loaded.selectedDetail}
          canCreate={canCreate}
          initialAnalysisId={analysisId ?? null}
          initialWorkAreaId={effectiveWorkAreaId}
          initialCurrentWorkOrderId={currentHint.currentWorkOrderId}
          scopeNotice={journeyScope.scopeNotice}
          currentHintNotice={currentHint.notice}
          initialBaselineSelector={exactHint.baseline}
          initialCurrentSelector={exactHint.current}
          exactHintNotice={exactHint.notice}
          broughtSelectors={broughtSelectors}
          catalogPair={catalogPair}
          visualContext={visualContext && visualContext.workAreaId === effectiveWorkAreaId ? visualContext : null}
          visualReturnHref={visualReturnHref}
          visualContextNotice={visualContextNotice}
        />
        {loaded.analyses.items.length === 0 && <AnalysisStartGuide
          workAreaId={effectiveWorkAreaId || null}
          siteId={siteId}
          workAreaCount={loaded.areas.workAreas.length}
          observationCount={loaded.attributedObservations.length}
          analysisCount={loaded.analyses.items.length}
          hasMoreAnalyses={loaded.analyses.nextCursor !== null}
          canCreate={canCreate}
          compact={loaded.areas.workAreas.length > 0 && loaded.attributedObservations.length >= 2}
        />}
      </> : <div className="flex flex-col gap-3">
        <ErrorState message={denied ? "현장 변화 분석을 조회할 권한이 없습니다. 현장 담당자에게 변화 분석 기록 조회 권한을 요청하세요." : missingDetail ? "선택한 분석 기록을 찾을 수 없거나 접근할 수 없습니다. 분석 목록에서 다른 기록을 확인하세요." : unavailable ? "이 환경에서는 현장 변화 분석 기능을 사용할 수 없습니다. 등록 자료 자체의 문제가 아닙니다." : "현장 변화 분석 정보를 불러오지 못했습니다."} tone={denied ? "high" : unavailable || missingDetail ? "idle" : "crit"} retryable={!denied && !unavailable && !missingDetail} retryAfterSeconds={retryAfterSeconds} />
        {missingDetail && <Link className="btn w-fit" href={fallbackScope ? `/sites/${encodeURIComponent(siteId)}/analysis?workAreaId=${encodeURIComponent(fallbackScope)}` : `/sites/${encodeURIComponent(siteId)}/analysis`}>분석 목록 보기</Link>}
        {unavailable && <>
          <p className="rounded-lg border border-line bg-surface px-4 py-2.5 text-[12px] leading-5 text-ink-2" role="status">분석 실행 환경이 준비되지 않아 계산 요청으로 이어지지 않습니다. 같은 구역의 등록 자료와 검사 상태는 확인할 수 있습니다.</p>
          <nav className="flex flex-wrap gap-2" aria-label="분석 불가 시 다음 확인">
            <Link className="btn" href={fallbackScope ? `/sites/${encodeURIComponent(siteId)}/spatial-assets?workAreaId=${encodeURIComponent(fallbackScope)}` : `/sites/${encodeURIComponent(siteId)}/spatial-assets`}>등록 자료 보기</Link>
            <Link className="btn" href={fallbackScope ? `/sites/${encodeURIComponent(siteId)}?workAreaId=${encodeURIComponent(fallbackScope)}` : `/sites/${encodeURIComponent(siteId)}`}>현장 현황 보기</Link>
          </nav>
        </>}
      </div>}
    </div>
  </>;
}
