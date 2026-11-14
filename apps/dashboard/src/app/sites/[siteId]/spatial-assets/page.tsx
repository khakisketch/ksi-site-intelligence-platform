import { redirect } from "next/navigation";

import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import { listSpatialWorkspaceObservations } from "@/lib/core-api/spatial-workspace";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { resolveExplicitVisualPair } from "@/lib/site-workspace-entry";
import { buildWorkspaceServerFacts } from "../site-workspace-server-facts";
import { readScopedAsset } from "../materials/asset-reads";
import { exactMaterialsAssetRef, isMetadataOnly, type MaterialsSearchParams } from "../materials/materials-visual";

export const metadata = { title: "공간 · KSI" };

export default async function SpatialAssetsPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<MaterialsSearchParams>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const target = new URLSearchParams({ panel: "materials" });
  for (const key of ["workAreaId", "assetRef", "q", "kind", "state", "cursor", "info"] as const) {
    const value = query[key];
    for (const item of Array.isArray(value) ? value : value ? [value] : []) target.append(key, item);
  }

  const sideA = exactMaterialsAssetRef(query.visualAAssetRef);
  const sideB = exactMaterialsAssetRef(query.visualBAssetRef);
  if (query.visualAAssetRef !== undefined) target.set("assetRef", sideA ?? "invalid");
  if (sideA && sideB && sideA !== sideB && !Array.isArray(query.workAreaId)) {
    // The canonical viewer accepts only a pair bound to one authorized WorkArea
    // and two exact workspace observations. Check the bounded pair before moving it.
    try {
      const { workAreas } = await listWorkAreas(siteId, { includeArchived: true });
      const active = workAreas.filter((area) => area.status === "ACTIVE");
      const workAreaId = query.workAreaId || (active.length === 1 ? active[0].workAreaId : null);
      if (workAreaId && workAreas.some((area) => area.workAreaId === workAreaId)) {
        const [page, first, second] = await Promise.all([
          listSpatialWorkspaceObservations(siteId, workAreaId, { limit: 50 }),
          readScopedAsset(siteId, workAreaId, sideA),
          readScopedAsset(siteId, workAreaId, sideB),
        ]);
        const catalog = [first, second].filter((item): item is SpatialAssetCatalogItem => item !== null && isMetadataOnly(item));
        const facts = buildWorkspaceServerFacts({
          siteId, areas: workAreas, projection: { status: "ready", page }, analyses: null, workAreaId,
        });
        if (catalog.length === 2 && page.siteId === siteId && page.workAreaId === workAreaId
          && resolveExplicitVisualPair(facts, { workAreaId, visualAAssetRef: sideA, visualBAssetRef: sideB }, catalog).status === "ready") {
          target.set("workAreaId", workAreaId);
          target.set("mode", "compare");
          target.set("visualAAssetRef", sideA);
          target.set("visualBAssetRef", sideB);
        }
      }
    } catch {
      // Preserve the A selection and let the canonical page report its read state.
    }
  }

  redirect(`/sites/${encodeURIComponent(siteId)}?${target}`);
}
