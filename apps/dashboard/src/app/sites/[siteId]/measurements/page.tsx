import Link from "next/link";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { PageHeader } from "@/components/ui/PageHeader";
import { CoreApiError } from "@/lib/core-api/client";
import {
  getSurfaceProfileResult,
  listMeasurementFeatures,
  listSurfaceProfileJobs,
  type MeasurementFeatureRevision,
  type SurfaceProfileJobView,
} from "@/lib/core-api/measurement";
import { FEATURE_ID_PATTERN, JOB_ID_PATTERN } from "@/lib/core-api/measurement-types";
import { listSpatialAssets } from "@/lib/core-api/spatial-assets";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { availabilityText, failureText, resultErrorText } from "@/lib/measurement-copy";
import { requestRows } from "@/lib/measurement-requests";
import { captureDateLabel, chooseProfileJobs } from "@/lib/measurement-selection";
import { materialsHref } from "@/app/sites/[siteId]/materials/materials-visual";

import { AreaSelect } from "./AreaSelect";
import { ProfileRequests } from "./ProfileRequests";
import { MeasurementWorkbench, type LoadedSeries, type UnavailableDate } from "./MeasurementWorkbench";

export const metadata = { title: "측정 선 · KSI" };

type SearchValue = string | string[] | undefined;
type SearchParams = { workAreaId?: SearchValue; feature?: SearchValue; ref?: SearchValue; cur?: SearchValue };

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
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={basePath} />;

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
  const header = <PageHeader
    title="측정 선"
    headingLevel={2}
    actions={<Link href={`/sites/${encodeURIComponent(siteId)}`} className="btn btn-quiet">공간으로 돌아가기</Link>}
  />;
  const frame = (workAreaId: string | null) => <SiteHeader site={site} selectedEpochId={null} tab="space" scopedWorkAreaId={workAreaId} />;
  const shell = (workAreaId: string | null, body: React.ReactNode) => (
    <div className="flex flex-col">
      {frame(workAreaId)}
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-4 sm:p-5">{header}{body}</div>
    </div>
  );

  if (!permissions.includes("SITES_READ") || !permissions.includes("SPATIAL_DATA_READ")) {
    return shell(null, <ErrorState message={READ_PERMISSION_MESSAGE} tone="high" />);
  }

  const areaParam = single(query.workAreaId);
  if (Array.isArray(query.workAreaId) || Array.isArray(query.feature) || Array.isArray(query.ref) || Array.isArray(query.cur)) {
    return shell(null, <ErrorState message="주소의 선택 값이 올바르지 않습니다." tone="high" action={{ label: "처음으로", href: basePath }} />);
  }

  let areas: Awaited<ReturnType<typeof listWorkAreas>>;
  try {
    areas = await listWorkAreas(siteId, { includeArchived: true });
  } catch (error) {
    return shell(null, readError(error, "작업구역 목록을 불러오지 못했습니다."));
  }
  const selectedArea = areas.workAreas.find((area) => area.workAreaId === areaParam);
  const chooser = (
    <section className="rounded-lg border border-line bg-surface px-4 py-3">
      <form action={basePath} method="get" className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-56 flex-col gap-1 text-caption font-semibold" htmlFor="measurement-work-area">작업구역
          <AreaSelect key={areaParam ?? ""} value={areaParam ?? ""}>
            <option value="" disabled>작업구역을 선택하세요</option>
            {areas.workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}{area.status === "ARCHIVED" ? " · 보관됨" : ""}</option>)}
          </AreaSelect>
        </label>
        <noscript><button className="btn" type="submit">불러오기</button></noscript>
      </form>
      {areas.workAreas.length === 0 && <p className="mt-3 text-body text-ink-2">조회할 작업구역이 없습니다. 현장 담당자에게 작업구역 등록 여부를 확인하세요.</p>}
    </section>
  );
  if (areaParam && !selectedArea) {
    return shell(null, <>{chooser}<ErrorState message="작업구역을 확인할 수 없거나 접근 권한이 없습니다." tone="high" action={{ label: "다른 작업구역 선택", href: basePath }} /></>);
  }
  if (!selectedArea) return shell(null, <>{chooser}<p className="text-body text-ink-2">작업구역을 선택하면 저장한 측정 선을 볼 수 있습니다.</p></>);
  const workAreaId = selectedArea.workAreaId;
  // 선 그리기는 쓰기라서 권한이 있고 보관되지 않은 구역일 때만 연다. 모바일에서는 화면이 숨긴다.
  const canDraw = permissions.includes("SITES_WRITE") && selectedArea.status === "ACTIVE";
  const drawHref = `${basePath}/new?workAreaId=${encodeURIComponent(workAreaId)}`;

  let features: MeasurementFeatureRevision[];
  try {
    features = (await listMeasurementFeatures(siteId, workAreaId)).features
      .filter((feature) => feature.siteId === siteId && feature.workAreaId === workAreaId);
  } catch (error) {
    return shell(workAreaId, <>{chooser}{readError(error, "측정 선을 불러오지 못했습니다.")}</>);
  }
  if (features.length === 0) {
    return shell(workAreaId, <>{chooser}<EmptyState
      title="저장한 측정 선이 없습니다"
      description="측정 선을 저장하면 날짜별 높이 단면을 볼 수 있습니다."
      action={canDraw ? { label: "측정 선 그리기", href: drawHref, responsiveAction: "WORK_ORDERS_WRITE", desktopOnly: true, compactReason: "측정 선은 노트북에서 지도에 그립니다." } : undefined}
    /></>);
  }

  const featureParam = single(query.feature);
  const selected = (featureParam && FEATURE_ID_PATTERN.test(featureParam) ? features.find((feature) => feature.featureId === featureParam) : undefined) ?? features[0]!;

  let jobs: SurfaceProfileJobView[] = [];
  let jobsDisconnected = false;
  try {
    jobs = (await listSurfaceProfileJobs(siteId, workAreaId, { limit: JOB_LIST_LIMIT, featureId: selected.featureId })).items
      .filter((job) => job.siteId === siteId && job.workAreaId === workAreaId);
  } catch (error) {
    // 단면 작업이 연결되지 않은 환경은 경로 자체가 없다. 빈 결과로 위장하지 않고 그대로 알린다.
    if (error instanceof CoreApiError && error.status === 404) jobsDisconnected = true;
    else return shell(workAreaId, <>{chooser}{readError(error, "단면 결과를 불러오지 못했습니다.")}</>);
  }

  // 날짜 이름표용 자료 목록. 실패해도 단면은 그대로 두고 날짜만 "촬영 시기 미상"으로 둔다.
  const dateByAsset = new Map<string, string | null>();
  const dsmAssets: string[] = [];
  try {
    const catalog = await listSpatialAssets(siteId, workAreaId, { limit: 50 });
    if (catalog.siteId === siteId && catalog.workAreaId === workAreaId) {
      for (const asset of catalog.assets) {
        if (asset.kind === "dsm" && asset.lifecycleState === "SEALED") dsmAssets.push(asset.assetRef);
        dateByAsset.set(asset.assetRef, captureDateLabel({ captureDate: asset.declared.captureDate, captureStartedAt: asset.declared.captureStartedAt }));
      }
    }
  } catch { /* 이름표만 잃는다 */ }
  const labelOf = (assetRef: string) => {
    const date = dateByAsset.get(assetRef) ?? null;
    return { label: date ?? "촬영 시기 미상", date };
  };

  // 날짜(자료)별 요청 상태. 단면 기능이 연결되지 않은 환경에서는 요청 패널을 열지 않는다.
  const requestable = jobsDisconnected ? [] : requestRows({
    assets: dsmAssets.map((assetRef) => ({ assetRef, label: labelOf(assetRef).label })),
    jobs,
    feature: { featureId: selected.featureId, revision: selected.revision, lineDigest: selected.lineDigest },
  }).map((row) => ({ ...row, assetHref: materialsHref(siteId, workAreaId, { assetRef: row.assetRef }) }));
  const requests = requestable.length > 0 && (
    <ProfileRequests
      key={`${selected.featureId}:${selected.revision}`}
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
    requestedRef: refParam === "" || (refParam && JOB_ID_PATTERN.test(refParam)) ? refParam : undefined,
    requestedCur: curParam && JOB_ID_PATTERN.test(curParam) ? curParam : undefined,
  });

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
      if (view.job.jobId !== jobId || view.result.assetRef !== option.assetRef || view.result.lineDigest !== selected.lineDigest) {
        unavailable.push({ role, label: option.label, message: "결과가 요청한 선과 일치하지 않아 표시하지 않습니다." });
        return null;
      }
      return { jobId, label: option.label, result: view.result, vertical: view.job.receipt?.verticalReference ?? null };
    } catch (error) {
      unavailable.push({ role, label: option.label, message: resultErrorText(error instanceof CoreApiError ? error.status : 500) });
      return null;
    }
  }
  const [baseline, current] = await Promise.all([load("ref", choice.refJobId), load("cur", choice.curJobId)]);

  const notes: string[] = [];
  if (choice.otherRevisionCount > 0) notes.push(`선을 고치기 전 개정의 결과 ${choice.otherRevisionCount}건은 이 화면에서 제외했습니다.`);
  if (choice.pendingCount > 0) notes.push(`처리 중인 단면 ${choice.pendingCount}건이 있습니다. 끝나면 새로 고쳐 확인하세요.`);

  const failureNotices = choice.failures.map((failure) => (
    <InlineNotice key={failure.label} tone="high" role="alert"><span className="font-semibold">{failure.label}</span> {failureText(failure.reason)}</InlineNotice>
  ));

  const hasAny = baseline !== null || current !== null;
  return shell(workAreaId, <>
    {chooser}
    {canDraw && (
      <div className="hidden justify-end gap-2 lg:flex">
        <Link href={`${drawHref}&featureId=${encodeURIComponent(selected.featureId)}`} className="btn">이 선 고치기</Link>
        <Link href={drawHref} className="btn">새 선 그리기</Link>
      </div>
    )}
    {jobsDisconnected && <InlineNotice tone="high" role="alert">이 환경에서는 단면 기능이 연결되어 있지 않아 결과를 읽을 수 없습니다.</InlineNotice>}
    {failureNotices}
    {!hasAny && requests}
    {hasAny
      ? <MeasurementWorkbench
        key={`${selected.featureId}:${choice.refJobId ?? ""}:${choice.curJobId ?? ""}`}
        workAreaId={workAreaId}
        features={features.map((feature) => ({ featureId: feature.featureId, label: `${feature.name} · 개정 ${feature.revision}` }))}
        selectedFeatureId={selected.featureId}
        featureName={selected.name}
        featureRevision={selected.revision}
        dateOptions={choice.options.map((option) => ({ jobId: option.jobId, label: option.label }))}
        refJobId={choice.refJobId}
        curJobId={choice.curJobId}
        baseline={baseline}
        current={current}
        unavailable={unavailable}
        notes={notes}
      />
      : <>
        {unavailable.map((item) => <InlineNotice key={item.label} tone="high" role="alert"><span className="font-semibold">{item.label}</span> {item.message}</InlineNotice>)}
        {!jobsDisconnected && unavailable.length === 0 && <EmptyState title="이 선의 단면 결과가 없습니다" description={`${selected.name}의 날짜별 단면 결과가 생기면 이곳에 표시됩니다.`} />}
        {notes.map((note) => <p key={note} className="text-micro text-ink-muted">{note}</p>)}
      </>}
    {hasAny && requests}
  </>);
}
