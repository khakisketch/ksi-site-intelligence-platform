import Link from "next/link";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { CoreApiError } from "@/lib/core-api/client";
import { listMeasurementFeatures } from "@/lib/core-api/measurement";
import { ASSET_REF_PATTERN, FEATURE_ID_PATTERN } from "@/lib/core-api/measurement-types";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { getMeasurementSource, measurementListHref, measurementLoginReturn } from "@/lib/measurement-source";
import { toDisplayVertices } from "@/lib/geo/display-geometry";
import { proj4 } from "@/lib/geo/proj4-defs";
import { registerKnownProjections } from "@/lib/geo/proj4-defs";
import { captureDateLabel } from "@/lib/measurement-selection";
import { savedLineToEditorVertices, type LineVertex } from "@/lib/measurement-line";
import { parseFootprintWkt } from "../../site-spatial";
import { materialsHref } from "../../materials/materials-visual";

import { LineEditor } from "./LineEditor";

export const metadata = { title: "측정 선 그리기 · KSI" };

type SearchValue = string | string[] | undefined;

function single(value: SearchValue): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function project(crs: string, vertex: readonly [number, number]): [number, number] {
  registerKnownProjections();
  const [lon, lat] = proj4(crs, "EPSG:4326", [vertex[0], vertex[1]]);
  return [lon!, lat!];
}

/** 측정 선을 새로 그리거나(`featureId` 없음) 새 개정으로 고친다. 저장하지 않는 한 아무것도 쓰지 않는다. */
export default async function NewMeasurementLinePage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ workAreaId?: SearchValue; featureId?: SearchValue; assetRef?: SearchValue; feature?: SearchValue; ref?: SearchValue; cur?: SearchValue; comparison?: SearchValue }>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const listPath = `/sites/${encodeURIComponent(siteId)}/measurements`;
  const areaParam = single(query.workAreaId);
  const featureParam = single(query.featureId);
  const assetParam = single(query.assetRef);
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={measurementLoginReturn(siteId, true, query)} />;

  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="현장 정보를 불러오지 못했습니다." tone="crit" retryable /></div>;
  }

  const workAreaId = areaParam ?? null;
  const returnHref = measurementListHref(siteId, {
    workAreaId: query.workAreaId,
    feature: query.feature === undefined ? query.featureId : query.feature,
    assetRef: query.assetRef,
    ref: query.ref,
    cur: query.cur,
    comparison: query.comparison,
  });
  const shell = (body: React.ReactNode) => (
    <div className="flex flex-col">
      <SiteHeader site={site} selectedEpochId={null} tab="space" scopedWorkAreaId={workAreaId} />
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-4 sm:p-5">
        <PageHeader
          title={featureParam ? "측정 선 고치기" : "측정 선 그리기"}
          headingLevel={2}
          actions={<Link href={returnHref} className="btn btn-quiet">측정 선으로 돌아가기</Link>}
        />
        {body}
      </div>
    </div>
  );

  const permissions = session.principal.permissions;
  if (!permissions.includes("SITES_READ") || !permissions.includes("SITES_WRITE")) {
    return shell(<ErrorState message="측정 선을 저장할 권한이 없습니다. 현장 담당자에게 권한을 요청하세요." tone="high" />);
  }
  if (!areaParam || Array.isArray(query.workAreaId) || Array.isArray(query.featureId) || Array.isArray(query.assetRef)) {
    return shell(<ErrorState message="작업구역을 먼저 선택하세요." tone="high" action={{ label: "측정 선으로", href: listPath }} />);
  }
  if (assetParam !== undefined && !ASSET_REF_PATTERN.test(assetParam)) {
    return shell(<ErrorState message="선택한 자료의 주소가 올바르지 않습니다." tone="high" action={{ label: "측정 선으로", href: `${listPath}?workAreaId=${encodeURIComponent(areaParam)}` }} />);
  }
  if (featureParam !== undefined && !FEATURE_ID_PATTERN.test(featureParam)) {
    return shell(<ErrorState message="고칠 선의 주소가 올바르지 않습니다." tone="high" action={{ label: "측정 선으로", href: `${listPath}?workAreaId=${encodeURIComponent(areaParam)}` }} />);
  }

  let areas: Awaited<ReturnType<typeof listWorkAreas>>;
  try {
    areas = await listWorkAreas(siteId, { includeArchived: true });
  } catch {
    return shell(<ErrorState message="작업구역을 불러오지 못했습니다." retryable />);
  }
  const area = areas.workAreas.find((candidate) => candidate.workAreaId === areaParam && candidate.siteId === siteId);
  if (!area) return shell(<ErrorState message="작업구역을 확인할 수 없거나 접근 권한이 없습니다." tone="high" action={{ label: "측정 선으로", href: listPath }} />);
  if (area.status !== "ACTIVE") {
    return shell(<ErrorState message="보관된 작업구역에는 측정 선을 저장할 수 없습니다. 저장한 선은 측정 선 화면에서 볼 수 있습니다." tone="high" action={{ label: "측정 선으로", href: `${listPath}?workAreaId=${encodeURIComponent(areaParam)}` }} />);
  }

  const editorParams = new URLSearchParams({ workAreaId: areaParam });
  if (featureParam && FEATURE_ID_PATTERN.test(featureParam)) editorParams.set("featureId", featureParam);
  const generalEditorHref = `${listPath}/new?${editorParams}`;

  let source: Awaited<ReturnType<typeof getMeasurementSource>> = null;
  if (assetParam) {
    try {
      source = await getMeasurementSource(siteId, areaParam, assetParam);
    } catch (error) {
      const message = error instanceof CoreApiError && (error.status === 403 || error.status === 404)
        ? "선택한 자료를 읽을 권한이 없거나 이 작업구역에서 확인할 수 없습니다."
        : "선택한 자료 정보를 불러오지 못했습니다.";
      return shell(<div className="flex flex-col gap-3">
        <ErrorState
          message={message}
          tone="high"
          retryable={!(error instanceof CoreApiError && (error.status === 403 || error.status === 404))}
          action={{ label: "자료 상세에서 다시 선택", href: materialsHref(siteId, areaParam, { assetRef: assetParam }) }}
        />
        <Link href={generalEditorHref} className="btn w-fit">자료 없이 측정선 편집기 열기</Link>
      </div>);
    }
    if (!source) {
      return shell(<div className="flex flex-col gap-3">
        <ErrorState
          message="선택한 자료가 검사된 DSM이 아니거나, 등록 취소·교체되어 측정선 출발점으로 사용할 수 없습니다."
          tone="high"
          action={{ label: "자료 목록에서 다시 선택", href: materialsHref(siteId, areaParam) }}
        />
        <Link href={generalEditorHref} className="btn w-fit">자료 없이 측정선 편집기 열기</Link>
      </div>);
    }
  }

  const display = toDisplayVertices(area.polygon, area.crs);
  const ring: LineVertex[] | null = display.ok
    ? [...display.vertices.map((vertex): LineVertex => [vertex.lonDeg, vertex.latDeg]), [display.vertices[0]!.lonDeg, display.vertices[0]!.latDeg]]
    : null;
  let sourceRing: LineVertex[] | null = null;
  if (source?.inspection.raster) {
    const parsed = parseFootprintWkt(source.inspection.raster.footprintWkt);
    if (parsed) {
      const converted = toDisplayVertices({ type: "Polygon", coordinates: [[...parsed, parsed[0]]] }, source.inspection.raster.observedCrsIdentifier);
      if (converted.ok) sourceRing = converted.vertices.map((vertex): LineVertex => [vertex.lonDeg, vertex.latDeg]);
    }
  }
  const sourceDate = source ? captureDateLabel({
    captureDate: source.declared.captureDate,
    captureStartedAt: source.declared.captureStartedAt,
  }) : null;

  let initialVertices: LineVertex[] = [];
  let initialName = "";
  let editing: { featureId: string; revision: number } | null = null;
  let convertedFromCrs: string | null = null;
  if (featureParam !== undefined) {
    let features: Awaited<ReturnType<typeof listMeasurementFeatures>>["features"];
    try {
      features = (await listMeasurementFeatures(siteId, areaParam)).features;
    } catch {
      return shell(<ErrorState message="고칠 선을 불러오지 못했습니다." retryable />);
    }
    const feature = features.find((candidate) => candidate.featureId === featureParam && candidate.siteId === siteId && candidate.workAreaId === areaParam);
    if (!feature) return shell(<ErrorState message="고칠 선을 찾을 수 없습니다. 이미 지워졌거나 권한이 없을 수 있습니다." tone="high" action={{ label: "측정 선으로", href: `${listPath}?workAreaId=${encodeURIComponent(areaParam)}` }} />);
    const converted = savedLineToEditorVertices(feature.line, project);
    if (!converted.ok) return shell(<ErrorState message={converted.reason} tone="high" action={{ label: "측정 선으로", href: `${listPath}?workAreaId=${encodeURIComponent(areaParam)}&feature=${encodeURIComponent(feature.featureId)}` }} />);
    initialVertices = converted.vertices;
    initialName = feature.name;
    editing = { featureId: feature.featureId, revision: feature.revision };
    convertedFromCrs = converted.converted ? feature.line.crs : null;
  }

  return shell(
    <LineEditor
      key={`${areaParam}:${featureParam ?? ""}:${source?.assetRef ?? ""}`}
      siteId={siteId}
      workAreaId={area.workAreaId}
      areaName={area.name}
      ring={ring}
      initialVertices={initialVertices}
      initialName={initialName}
      editing={editing}
      convertedFromCrs={convertedFromCrs}
      source={source ? {
        assetRef: source.assetRef,
        fileName: source.declared.fileName,
        captureDate: sourceDate,
        footprint: sourceRing,
      } : null}
      focusRing={editing ? null : sourceRing ?? ring}
      returnHref={returnHref}
    />,
  );
}
