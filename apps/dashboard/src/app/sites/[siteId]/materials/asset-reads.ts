import { getSpatialAsset, type SpatialAssetCatalogItem, type SpatialAssetCatalogPage } from "@/lib/core-api/spatial-assets";
import { getExternalReconstructionSubmission } from "@/lib/core-api/external-reconstruction";
import { validateRegistrationHistory } from "@/lib/registration-history";

export function scopeMaterialsPage(page: SpatialAssetCatalogPage, siteId: string, workAreaId: string): SpatialAssetCatalogPage {
  if (page.siteId !== siteId || page.workAreaId !== workAreaId) throw new Error("Unbound materials page");
  return { ...page, assets: page.assets.filter((item) => item.siteId === siteId && item.workAreaId === workAreaId) };
}

export async function readScopedAsset(siteId: string, workAreaId: string, assetRef: string): Promise<SpatialAssetCatalogItem | null> {
  try {
    const item = await getSpatialAsset(siteId, workAreaId, assetRef);
    return item.siteId === siteId && item.workAreaId === workAreaId && item.assetRef === assetRef ? item : null;
  } catch {
    return null;
  }
}

export async function readAssetHistory(item: SpatialAssetCatalogItem, organizationId: string) {
  try {
    const record = await getExternalReconstructionSubmission(item.workOrderId, item.submissionRef, item.revision);
    return validateRegistrationHistory(record, {
      siteId: item.siteId,
      organizationId,
      submissionRef: item.submissionRef,
      observationEpochId: item.observationEpochId,
      revision: item.revision,
    });
  } catch {
    return { kind: "unavailable" as const };
  }
}
