import Link from "next/link";
import { profileInputNotice } from "@/lib/asset-next-steps";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { siteDataHref } from "@/components/nav/site-context";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { PageHeader } from "@/components/ui/PageHeader";
import { CoreApiError } from "@/lib/core-api/client";
import {
  getMeasurementFeatureRevision,
  getSurfaceProfileComparisonWithToken,
  getSurfaceProfileJob,
  getSurfaceProfileResult,
  listMeasurementFeatures,
  listSurfaceProfileJobs,
  type MeasurementFeatureRevision,
  type SurfaceProfileJobView,
} from "@/lib/core-api/measurement";
import { ASSET_REF_PATTERN, FEATURE_ID_PATTERN, JOB_ID_PATTERN, type SurfaceProfileComparison } from "@/lib/core-api/measurement-types";
import { getSessionToken } from "@/lib/core-api/session";
import { listSpatialAssets, type SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { availabilityText, failureText, resultErrorText } from "@/lib/measurement-copy";
import { requestRows } from "@/lib/measurement-requests";
import { captureDateLabel, chooseProfileJobs } from "@/lib/measurement-selection";
import { getMeasurementSource, measurementLoginReturn } from "@/lib/measurement-source";
import { siteTabHref } from "@/lib/operator-journey";
import { materialsHref } from "@/app/sites/[siteId]/materials/materials-visual";

import { MeasurementScope } from "./MeasurementScope";
import { ProfileRequests } from "./ProfileRequests";
import { MeasurementWorkbench, type LoadedSeries, type UnavailableDate } from "./MeasurementWorkbench";

export const metadata = { title: "측정 선 · KSI" };

type SearchValue = string | string[] | undefined;
type SearchParams = { workAreaId?: SearchValue; assetRef?: SearchValue; feature?: SearchValue; ref?: SearchValue; cur?: SearchValue; comparison?: SearchValue };

/** Core가 한 번에 돌려주는 작업 수. 단면 작업 목록의 안전한 최소 한도에 맞춘다. */
const JOB_LIST_LIMIT = 8;
const READ_PERMISSION_MESSAGE = "이 현장의 측정 선과 단면을 볼 권한이 없습니다. 현장 담당자에게 접근 권한을 요청하세요.";

function single(value: SearchValue): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function readError(error: unknown, fallback: string) {
  if (error instanceof CoreApiError) {
    if (error.status === 403) return <ErrorState message={READ_PERMISSION_MESSAGE} tone="high" />;
    if (error.status === 404) return <ErrorState message="작업구역을 확인할 수 없거나 접근 권한이 없습니다." tone="high" />;
    return <ErrorState message={fallback} retryable retryAfterSeconds={error.retryAfterSeconds} />;
  }
  return <ErrorState message={fallback} retryable />;
}

export default async function MeasurementsPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const basePath = `/sites/${encodeURIComponent(siteId)}/measurements`;
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={measurementLoginReturn(siteId, false, query)} />;

  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState
      message={error instanceof CoreApiError && error.status === 403 ? "현장 조회 권한이 없습니다." : "현장 정보를 불러오지 못했습니다."}
      tone={error instanceof CoreApiError && error.status === 403 ? "high" : "crit"}
      retryable={!(error instanceof CoreApiError && error.status === 403)}
      retryAfterSeconds={error instanceof CoreApiError ? error.retryAfterSeconds : undefined}
    /></div>;
  }

  const permissions = session.principal.permissions;
  let source: SpatialAssetCatalogItem | null = null;
  const shell = (workAreaId: string | null, body: React.ReactNode) => (
    <div className="flex flex-col">
      <SiteHeader site={site} selectedEpochId={null} tab="space" scopedWorkAreaId={workAreaId} scopedAssetRef={source?.assetRef} />
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-4 sm:p-5">
        <PageHeader title="측정 선" headingLevel={2} actions={
          <Link href={siteTabHref(siteId, "space", {}, { workAreaId, assetRef: source?.assetRef ?? null })} className="btn btn-quiet">공간으로 돌아가기</Link>
        } />
        {body}
      </div>
    </div>
  );

  if (!permissions.includes("SITES_READ") || !permissions.includes("SPATIAL_DATA_READ")) {
    return shell(null, <ErrorState message={READ_PERMISSION_MESSAGE} tone="high" />);
  }

  const areaParam = single(query.workAreaId);
  const sourceRef = single(query.assetRef);
  const featureParam = single(query.feature);
  const decisionId = single(query.comparison);
  const ref = single(query.ref);
  const cur = single(query.cur);
  if ([query.workAreaId, query.assetRef, query.feature, query.ref, query.cur, query.comparison].some(Array.isArray)
    || (query.assetRef !== undefined && (!areaParam || !ASSET_REF_PATTERN.test(sourceRef ?? "") || decisionId !== undefined))
    || (featureParam !== undefined && !FEATURE_ID_PATTERN.test(featureParam)) || (query.comparison !== undefined && (
    !decisionId?.trim() || decisionId.length > 255 || !areaParam
    || !FEATURE_ID_PATTERN.test(single(query.feature) ?? "") || !JOB_ID_PATTERN.test(ref ?? "")
    || !JOB_ID_PATTERN.test(cur ?? "") || ref === cur
  ))) {
    return shell(null, <ErrorState message="주소의 선택 값이 올바르지 않습니다." tone="high" action={{ label: "처음으로", href: basePath }} />);
  }

  let areas: Awaited<ReturnType<typeof listWorkAreas>>;
  try {
    areas = await listWorkAreas(siteId, { includeArchived: true });
  } catch (error) {
    return shell(null, readError(error, "작업구역 목록을 불러오지 못했습니다."));
  }
  const selectedArea = areas.workAreas.find((area) => area.workAreaId === areaParam);
  const chooser = (features: MeasurementFeatureRevision[] = [], current?: MeasurementFeatureRevision) => <MeasurementScope
    siteId={siteId} areas={areas.workAreas.map(({ workAreaId, name, status }) => ({ workAreaId, name, status }))}
    areaId={selectedArea?.workAreaId} featureId={current?.featureId}
    lines={features.map((feature) => {
      const shown = current?.featureId === feature.featureId ? current : feature;
      return { featureId: shown.featureId, label: `${shown.name} · 개정 ${shown.revision}` };
    })}
    source={source ? { assetRef: source.assetRef, fileName: source.declared.fileName, date: captureDateLabel(source.declared) } : null}
  />;
  if (areaParam && !selectedArea) {
    return shell(null, <>{chooser()}<ErrorState message="작업구역을 확인할 수 없거나 접근 권한이 없습니다." tone="high" action={{ label: "다른 작업구역 선택", href: basePath }} /></>);
  }
  if (!selectedArea) return shell(null, <>{chooser()}<p className="text-body text-ink-2">작업구역을 선택하면 저장한 측정 선을 볼 수 있습니다.</p></>);
  const workAreaId = selectedArea.workAreaId;
  const scopeQuery = new URLSearchParams({ workAreaId });
  if (sourceRef) {
    const returnToData = { label: "구역 자료 보기", href: siteDataHref(siteId, { workAreaId }) };
    try {
      source = await getMeasurementSource(siteId, workAreaId, sourceRef);
    } catch (error) {
      if (!(error instanceof CoreApiError && [403, 404, 410].includes(error.status))) {
        return shell(workAreaId, <>{chooser()}<ErrorState message="선택한 DSM을 불러오지 못했습니다." action={returnToData} retryable /></>);
      }
    }
    if (!source) return shell(workAreaId, <>{chooser()}<ErrorState message="선택한 DSM을 이 작업구역에서 열 수 없습니다. 자료의 검사 상태와 읽기 권한을 확인하세요." action={returnToData} tone="high" /></>);
    scopeQuery.set("assetRef", source.assetRef);
  }
  // 선 그리기는 쓰기라서 권한이 있고 보관되지 않은 구역일 때만 연다. 모바일에서는 화면이 숨긴다.
  const canDraw = permissions.includes("SITES_WRITE") && selectedArea.status === "ACTIVE";
  const drawHref = `${basePath}/new?${scopeQuery}`;

  let features: MeasurementFeatureRevision[];
  try {
    features = (await listMeasurementFeatures(siteId, workAreaId)).features
      .filter((feature) => feature.siteId === siteId && feature.workAreaId === workAreaId);
  } catch (error) {
    return shell(workAreaId, <>{chooser()}{readError(error, "측정 선을 불러오지 못했습니다.")}</>);
  }
  if (features.length === 0) {
    return shell(workAreaId, <>{chooser()}<EmptyState
      title="저장한 측정 선이 없습니다"
      description="측정 선을 저장하면 날짜별 높이 단면을 볼 수 있습니다."
      action={canDraw ? { label: "측정 선 그리기", href: drawHref, responsiveAction: "WORK_ORDERS_WRITE", desktopOnly: true, compactReason: "측정 선은 노트북에서 지도에 그립니다." } : undefined}
    /></>);
  }

  const latest = featureParam ? features.find((feature) => feature.featureId === featureParam) : features[0];
  if (!latest) return shell(workAreaId, <>{chooser(features)}<ErrorState message="이 작업구역에서 선택한 측정 선을 찾을 수 없습니다." action={{ label: "측정 선 다시 선택", href: `${basePath}?${scopeQuery}` }} tone="high" /></>);
  let selected = latest;

  let jobs: SurfaceProfileJobView[] = [];
  let jobsDisconnected = false;
  let comparisonError: string | null = null;
  try {
    const options = { limit: JOB_LIST_LIMIT, featureId: selected.featureId };
    const sourceOptions = { ...options, featureRevision: selected.revision, assetRef: source?.assetRef };
    const [recent, focused] = await Promise.all([
      listSurfaceProfileJobs(siteId, workAreaId, options),
      source ? listSurfaceProfileJobs(siteId, workAreaId, sourceOptions) : null,
    ]);
    const sourceJobs = [...(focused?.items ?? [])];
    if (source && sourceJobs.length === JOB_LIST_LIMIT) {
      // A run of later retries can push an active or completed job out of the recent page.
      const missingGroups = (["ACTIVE", "COMPLETED"] as const).filter((group) => !sourceJobs.some((job) => group === "ACTIVE"
        ? job.executionState === "QUEUED" || job.executionState === "RUNNING" : job.executionState === "COMPLETED"));
      const older = await Promise.all(missingGroups.map((executionGroup) =>
        listSurfaceProfileJobs(siteId, workAreaId, { ...sourceOptions, limit: 1, executionGroup })));
      for (const page of older) sourceJobs.push(...page.items);
    }
    const entries = focused ? [...new Map([...recent.items, ...sourceJobs].map((job) => [job.jobId, job])).values()] : recent.items;
    jobs = entries.filter((job) => job.siteId === siteId && job.workAreaId === workAreaId);
  } catch (error) {
    // 단면 작업이 연결되지 않은 환경은 경로 자체가 없다. 빈 결과로 위장하지 않고 그대로 알린다.
    if (error instanceof CoreApiError && error.status === 404) jobsDisconnected = true;
    else return shell(workAreaId, <>{chooser(features, selected)}{readError(error, "단면 결과를 불러오지 못했습니다.")}</>);
  }

  if ((decisionId || source) && !jobsDisconnected) {
    const missing = [...new Set([ref, cur])].filter((jobId): jobId is string => !!jobId && JOB_ID_PATTERN.test(jobId) && !jobs.some((job) => job.jobId === jobId));
    const pinned = await Promise.allSettled(missing.map((id) => getSurfaceProfileJob(siteId, workAreaId, id)));
    for (const read of pinned) {
      if (read.status === "fulfilled") jobs.push(read.value);
      else comparisonError = "이 주소에 저장된 단면을 모두 읽을 수 없습니다.";
    }
  }
  if (decisionId && ref && cur && !jobsDisconnected) {
    const before = jobs.find((job) => job.jobId === ref)?.feature;
    const after = jobs.find((job) => job.jobId === cur)?.feature;
    if (before && after && before.featureId === featureParam && before.featureId === latest.featureId
      && before.featureId === after.featureId && before.revision === after.revision
      && before.lineDigest === after.lineDigest && before.revision < latest.revision) {
      try {
        selected = await getMeasurementFeatureRevision(siteId, workAreaId, before);
      } catch {
        comparisonError = "이 비교에 저장된 측정 선 개정을 읽을 수 없습니다.";
      }
    }
  }
  const historical = selected.revision !== latest.revision;

  // 날짜 이름표용 자료 목록. 실패해도 단면은 그대로 두고 날짜만 "촬영 시기 미상"으로 둔다.
  const dateByAsset = new Map<string, string | null>();
  const noticeByAsset = new Map<string, string | null>();
  const dsmAssets: string[] = [];
  try {
    const catalog = await listSpatialAssets(siteId, workAreaId, { limit: 50, order: "capture-desc" });
    if (catalog.siteId === siteId && catalog.workAreaId === workAreaId) {
      for (const asset of catalog.assets) {
        if (asset.kind === "dsm" && asset.lifecycleState === "SEALED") dsmAssets.push(asset.assetRef);
        noticeByAsset.set(asset.assetRef, profileInputNotice(asset.inspection));
        dateByAsset.set(asset.assetRef, captureDateLabel({ captureDate: asset.declared.captureDate, captureStartedAt: asset.declared.captureStartedAt }));
      }
    }
  } catch { /* 이름표만 잃는다 */ }
  if (source) {
    dateByAsset.set(source.assetRef, captureDateLabel(source.declared));
    noticeByAsset.set(source.assetRef, profileInputNotice(source.inspection));
  }
  const labelOf = (assetRef: string) => {
    const date = dateByAsset.get(assetRef) ?? null;
    return { label: date ?? "촬영 시기 미상", date };
  };

  // 날짜(자료)별 요청 상태. 단면 기능이 연결되지 않은 환경에서는 요청 패널을 열지 않는다.
  const requestable = jobsDisconnected ? [] : requestRows({
    assets: (source ? [source.assetRef] : dsmAssets).map((assetRef) => ({ assetRef, label: labelOf(assetRef).label })),
    jobs,
    feature: { featureId: selected.featureId, revision: selected.revision, lineDigest: selected.lineDigest },
  }).map((row) => ({
    ...row, requestNotice: noticeByAsset.get(row.assetRef),
    assetHref: source ? siteDataHref(siteId, { workAreaId, assetRef: row.assetRef }) : materialsHref(siteId, workAreaId, { assetRef: row.assetRef }),
  }));
  const requests = requestable.length > 0 && (
    <ProfileRequests
      key={`${selected.featureId}:${selected.revision}:${source?.assetRef ?? ""}`}
      siteId={siteId}
      workAreaId={workAreaId}
      feature={{ featureId: selected.featureId, revision: selected.revision, lineDigest: selected.lineDigest }}
      rows={requestable}
      canRequest={permissions.includes("SITES_WRITE") && permissions.includes("SPATIAL_DATA_REQUEST") && selectedArea.status === "ACTIVE"}
    />
  );

  const refParam = single(query.ref);
  const curParam = single(query.cur);
  const choice = chooseProfileJobs({
    jobs,
    feature: selected,
    labelOf,
    sourceAssetRef: source?.assetRef,
    requestedRef: refParam === "" || (refParam && JOB_ID_PATTERN.test(refParam)) ? refParam : undefined,
    requestedCur: source || (curParam && JOB_ID_PATTERN.test(curParam)) ? curParam : undefined,
  });
  if (source && cur !== undefined && !choice.curJobId) {
    comparisonError = "주소에 지정된 단면을 선택한 DSM과 측정 선에서 열 수 없습니다.";
  }
  const unavailable: UnavailableDate[] = [];
  async function load(role: "ref" | "cur", jobId: string | null): Promise<LoadedSeries | null> {
    if (!jobId) return null;
    const option = choice.options.find((candidate) => candidate.jobId === jobId);
    if (!option) return null;
    const blocked = availabilityText(option.availability);
    if (blocked) {
      unavailable.push({ role, label: option.label, message: blocked });
      return null;
    }
    try {
      const view = await getSurfaceProfileResult(siteId, workAreaId, jobId);
      // 결과가 요청한 작업·선·자료에 정확히 묶였을 때만 보인다.
      if (view.job.jobId !== jobId
        || view.job.feature.featureId !== selected.featureId
        || view.job.feature.revision !== selected.revision
        || view.job.feature.lineDigest !== selected.lineDigest
        || view.result.feature?.featureId !== selected.featureId
        || view.result.feature.revision !== selected.revision
        || view.result.feature.lineDigest !== selected.lineDigest
        || view.result.assetRef !== option.assetRef
        || view.result.lineDigest !== selected.lineDigest) {
        unavailable.push({ role, label: option.label, message: "결과가 요청한 선과 일치하지 않아 표시하지 않습니다." });
        return null;
      }
      return { jobId, label: option.label, result: view.result, vertical: view.job.receipt?.verticalReference ?? null };
    } catch (error) {
      unavailable.push({ role, label: option.label, message: resultErrorText(error instanceof CoreApiError ? error.status : 500) });
      return null;
    }
  }
  const currentRead = load("cur", choice.curJobId);
  const [baseline, current] = await Promise.all([
    source ? currentRead.then((value) => value ? load("ref", choice.refJobId) : null) : load("ref", choice.refJobId),
    currentRead,
  ]);
  let savedComparison: SurfaceProfileComparison | null = null;
  if (decisionId && !comparisonError) {
    if (!baseline || !current || ref !== baseline.jobId || cur !== current.jobId || featureParam !== selected.featureId) {
      comparisonError = "저장된 비교가 현재 측정 선 개정이나 선택한 날짜와 일치하지 않습니다.";
    } else {
      try {
        const saved = await getSurfaceProfileComparisonWithToken(siteId, workAreaId, {
          baselineJobId: baseline.jobId, currentJobId: current.jobId, decisionId,
        }, await getSessionToken());
        if (saved.result && (saved.result.baselineResultDigest !== baseline.result.resultDigest
          || saved.result.currentResultDigest !== current.result.resultDigest)) {
          comparisonError = "저장된 비교의 원본 단면이 달라 결과를 표시할 수 없습니다.";
        } else savedComparison = saved;
      } catch (error) {
        comparisonError = error instanceof CoreApiError && [403, 404, 409, 410].includes(error.status)
          ? "현재 자료나 승인 상태에서 이 비교를 열 수 없습니다. 날짜별 읽기 권한과 비교 승인을 확인하세요."
          : "저장된 비교를 불러오지 못했습니다. 잠시 후 다시 열어 주세요.";
      }
    }
  }

  // Carry the chosen line back into the list when canceling. Job IDs are
  // carried only when the operator explicitly chose them in the list; the
  // default pair must not become a pinned historical choice.
  const newLineParams = new URLSearchParams(scopeQuery);
  if (FEATURE_ID_PATTERN.test(selected.featureId)) newLineParams.set("feature", selected.featureId);
  if (refParam === "") newLineParams.set("ref", "");
  else if (refParam && JOB_ID_PATTERN.test(refParam) && choice.refJobId === refParam) newLineParams.set("ref", refParam);
  if (curParam && JOB_ID_PATTERN.test(curParam) && choice.curJobId === curParam) newLineParams.set("cur", curParam);
  if (decisionId && /^[\w.:-]{1,255}$/.test(decisionId) && savedComparison
    && newLineParams.has("ref") && newLineParams.has("cur")) {
    newLineParams.set("comparison", decisionId);
  }
  const newLineHref = `${basePath}/new?${newLineParams}`;
  const editLineParams = new URLSearchParams(newLineParams);
  editLineParams.set("featureId", selected.featureId);
  const editLineHref = `${basePath}/new?${editLineParams}`;

  const notes: string[] = [];
  if (!historical && choice.otherRevisionCount > 0) notes.push(`선을 고치기 전 개정의 결과 ${choice.otherRevisionCount}건은 이 화면에서 제외했습니다.`);
  if (choice.pendingCount > 0) notes.push(`처리 중인 단면 ${choice.pendingCount}건이 있습니다. 끝나면 새로 고쳐 확인하세요.`);

  const failureNotices = choice.failures.map((failure) => (
    <InlineNotice key={failure.label} tone="high" role="alert"><span className="font-semibold">{failure.label}</span> {failureText(failure.reason)}</InlineNotice>
  ));

  const hasAny = baseline !== null || current !== null;
  return shell(workAreaId, <>
    {chooser(features, selected)}
    {historical && <InlineNotice tone="info"><span>저장 당시 측정 선 개정 {selected.revision}을 보고 있습니다. </span>
      <Link className="underline" href={`${basePath}?${new URLSearchParams({ workAreaId, feature: latest.featureId })}`}>현재 개정 {latest.revision} 보기</Link>
    </InlineNotice>}
    {canDraw && !historical && (
      <div className="hidden justify-end gap-2 lg:flex">
        <Link href={editLineHref} className="btn">이 선 고치기</Link>
        <Link href={newLineHref} className="btn">새 선 그리기</Link>
      </div>
    )}
    {jobsDisconnected && <InlineNotice tone="high" role="alert">이 환경에서는 단면 기능이 연결되어 있지 않아 결과를 읽을 수 없습니다.</InlineNotice>}
    {failureNotices}
    {comparisonError && <InlineNotice tone="high" role="alert">{comparisonError}</InlineNotice>}
    {!hasAny && !historical && requests && <>
      {source && <h2 className="text-title font-bold tracking-tight break-words">{selected.name}</h2>}
      {requests}
    </>}
    {hasAny
      ? <MeasurementWorkbench
        siteId={siteId}
        sourceAssetRef={source?.assetRef}
        featureChooserExternal
        key={`${selected.featureId}:${choice.refJobId ?? ""}:${choice.curJobId ?? ""}:${savedComparison?.decisionDigest ?? ""}`}
        savedComparison={savedComparison}
        workAreaId={workAreaId}
        features={features.map((feature) => {
          const shown = feature.featureId === selected.featureId ? selected : feature;
          return { featureId: shown.featureId, label: `${shown.name} · 개정 ${shown.revision}` };
        })}
        selectedFeatureId={selected.featureId}
        featureName={selected.name}
        featureRevision={selected.revision}
        featureLineDigest={selected.lineDigest}
        canCompare={permissions.includes("SITES_WRITE") && permissions.includes("SPATIAL_DATA_READ")}
        canRequest={!historical && permissions.includes("SITES_WRITE") && permissions.includes("SPATIAL_DATA_REQUEST") && selectedArea.status === "ACTIVE"}
        dateOptions={choice.options.map((option) => ({ jobId: option.jobId, label: option.label, assetRef: option.assetRef }))}
        refJobId={choice.refJobId}
        curJobId={choice.curJobId}
        baseline={baseline}
        current={current}
        unavailable={unavailable}
        notes={notes}
      />
      : <>
        {unavailable.map((item) => <InlineNotice key={item.label} tone="high" role="alert"><span className="font-semibold">{item.label}</span> {item.message}</InlineNotice>)}
        {!source && !jobsDisconnected && unavailable.length === 0 && <EmptyState title="이 선의 단면 결과가 없습니다" description={`${selected.name}의 날짜별 단면 결과가 생기면 이곳에 표시됩니다.`} />}
        {notes.map((note) => <p key={note} className="text-micro text-ink-muted">{note}</p>)}
      </>}
    {hasAny && !historical && requests}
  </>);
}
