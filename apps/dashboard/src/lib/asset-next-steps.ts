/** 검사를 마친 자료에서 이어서 할 수 있는 일. 파일 정보가 확인된 자료에만 보인다. 분석 가능 여부는 말하지 않는다. */
import { siteTabHref } from "@/lib/operator-journey";
import { isAnalysisCrs } from "@/lib/geo/known-crs";

export type AssetNextStep = { key: "viewer" | "measurements"; label: string; href: string };

type InspectedAsset = {
  siteId: string;
  workAreaId: string;
  assetRef: string;
  kind: string;
  lifecycleState: string;
  inspection: { outcome: string | null; state: string; raster?: { observedCrsIdentifier: string } | null };
};

export function isMeasuredAsset(asset: InspectedAsset): boolean {
  return asset.lifecycleState === "SEALED" && asset.inspection.outcome === "MEASURED"
    && (asset.inspection.state === "INSPECTION_REPORTED" || asset.inspection.state === "COMPLETED");
}

/** Apply the worker's horizontal CRS rule to the inspected grid, independently of the submitted label. */
export function profileInputNotice(inspection: InspectedAsset["inspection"] | undefined): string | null {
  if (inspection?.outcome === "REJECTED") return "파일 검사에서 거부된 DSM입니다.";
  const crs = inspection?.raster?.observedCrsIdentifier;
  return crs && !isAnalysisCrs(crs) ? `이 DSM의 수평 좌표계(${crs})는 현재 단면 분석 지원 범위 밖입니다.` : null;
}

export function assetNextSteps(asset: InspectedAsset): AssetNextStep[] {
  if (!isMeasuredAsset(asset)) return [];
  const site = `/sites/${encodeURIComponent(asset.siteId)}`;
  const scope = { workAreaId: asset.workAreaId, assetRef: asset.assetRef };
  const steps: AssetNextStep[] = [{ key: "viewer", label: "공간에서 보기", href: siteTabHref(asset.siteId, "space", {}, scope) }];
  if (asset.kind === "dsm" && !profileInputNotice(asset.inspection)) {
    steps.push({ key: "measurements", label: "측정 선에서 단면 읽기", href: `${site}/measurements?${new URLSearchParams(scope)}` });
  }
  return steps;
}
