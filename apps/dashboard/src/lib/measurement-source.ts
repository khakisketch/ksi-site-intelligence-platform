import "server-only";

import { isMeasuredAsset } from "@/lib/asset-next-steps";
import { ASSET_REF_PATTERN, FEATURE_ID_PATTERN, JOB_ID_PATTERN } from "@/lib/core-api/measurement-types";
import { getSpatialAsset, type SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";

/** Resolve a selected DSM independently of the visible catalog page. This read never creates a HEIGHT decision. */
export async function getMeasurementSource(siteId: string, workAreaId: string, assetRef: string): Promise<SpatialAssetCatalogItem | null> {
  if (!ASSET_REF_PATTERN.test(assetRef)) return null;
  const item = await getSpatialAsset(siteId, workAreaId, assetRef);
  return item.siteId === siteId && item.workAreaId === workAreaId && item.assetRef === assetRef
    && item.kind === "dsm" && isMeasuredAsset(item) ? item : null;
}

type MeasurementNavigationQuery = Record<string, string | string[] | undefined>;

function measurementNavigationParams(query: MeasurementNavigationQuery, editor = false): URLSearchParams {
  const areaPattern = /^[\w.:-]{1,255}$/;
  const search = new URLSearchParams();
  const fields: Record<string, RegExp> = {
    workAreaId: areaPattern,
    assetRef: ASSET_REF_PATTERN,
    feature: FEATURE_ID_PATTERN,
    ref: JOB_ID_PATTERN,
    cur: JOB_ID_PATTERN,
    comparison: /^[\w.:-]{1,255}$/,
  };
  if (editor) fields.featureId = FEATURE_ID_PATTERN;
  for (const [key, pattern] of Object.entries(fields)) {
    const value = query[key];
    if (value === undefined) continue;
    if (key === "ref" && value === "") search.set(key, "");
    else if (typeof value === "string" && pattern.test(value)) search.set(key, value);
    else search.set(key, "invalid");
  }
  return search;
}

/** Build the fixed internal list route, retaining invalid selections as a harmless error marker. */
export function measurementListHref(siteId: string, query: MeasurementNavigationQuery): string {
  const path = `/sites/${encodeURIComponent(siteId)}/measurements`;
  const search = measurementNavigationParams(query);
  return search.size ? `${path}?${search}` : path;
}

/** Keep only navigation selections on the fixed internal return path when login is required. */
export function measurementLoginReturn(siteId: string, editor: boolean, query: MeasurementNavigationQuery): string {
  const path = `/sites/${encodeURIComponent(siteId)}/measurements${editor ? "/new" : ""}`;
  const search = measurementNavigationParams(query, editor);
  return search.size ? `${path}?${search}` : path;
}
