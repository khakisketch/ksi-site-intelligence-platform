import { beforeEach, expect, it, vi } from "vitest";

const core = vi.hoisted(() => ({ areas: vi.fn(), observations: vi.fn(), asset: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: (href: string) => { throw new Error(href); },
}));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: core.areas }));
vi.mock("@/lib/core-api/spatial-workspace", () => ({ listSpatialWorkspaceObservations: core.observations }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ getSpatialAsset: core.asset }));

import SpatialAssetsPage from "@/app/sites/[siteId]/spatial-assets/page";

const assetRef = `ksa-v1-${"a".repeat(64)}`;
const secondRef = `ksa-v1-${"b".repeat(64)}`;
const siteId = "site-1";
const workAreaId = "north";

function facts(ref: string, index: number) {
  return {
    assetRef: ref, siteId, workAreaId, workOrderId: `order-${index}`, observationEpochId: `epoch-${index}`,
    submissionRef: `submission-${index}`, revision: 1, kind: "ortho",
    dataAccess: "NOT_AVAILABLE_FROM_CATALOG", supportedActions: ["VIEW_METADATA"], analysisStatus: "NOT_EVALUATED",
  };
}

function legacy(searchParams: Record<string, string | string[]>) {
  return SpatialAssetsPage({ params: Promise.resolve({ siteId }), searchParams: Promise.resolve(searchParams) });
}

beforeEach(() => {
  vi.resetAllMocks();
  const pair = [facts(assetRef, 1), facts(secondRef, 2)];
  core.areas.mockResolvedValue({ workAreas: [{ workAreaId, status: "ACTIVE" }] });
  core.observations.mockResolvedValue({
    siteId, workAreaId,
    observations: pair.map((item) => ({ observationEpochId: item.observationEpochId, workOrderId: item.workOrderId, versions: [item] })),
  });
  core.asset.mockImplementation(async (_siteId: string, _areaId: string, ref: string) => pair.find((item) => item.assetRef === ref));
});

it("carries the legacy catalog selection, filters and cursor into the space materials panel", async () => {
  await expect(legacy({ workAreaId, assetRef, q: "north map", kind: "ortho", state: "inspected", cursor: "next/+=", info: "1" }))
    .rejects.toThrow(`/sites/site-1?panel=materials&workAreaId=north&assetRef=${assetRef}&q=north+map&kind=ortho&state=inspected&cursor=next%2F%2B%3D&info=1`);
  expect(core.asset).not.toHaveBeenCalled();
});

it("carries both exact proven refs into the shared two-time mode", async () => {
  await expect(legacy({ workAreaId, visualAAssetRef: assetRef, visualBAssetRef: secondRef }))
    .rejects.toThrow(`/sites/site-1?panel=materials&workAreaId=north&assetRef=${assetRef}&mode=compare&visualAAssetRef=${assetRef}&visualBAssetRef=${secondRef}`);
  expect(core.asset).toHaveBeenCalledTimes(2);
});

it("falls back to A when B cannot be bound to the same authorized scope", async () => {
  core.asset.mockImplementation(async (_siteId: string, _areaId: string, ref: string) =>
    ref === assetRef ? facts(assetRef, 1) : { ...facts(secondRef, 2), workAreaId: "foreign" });
  await expect(legacy({ workAreaId, visualAAssetRef: assetRef, visualBAssetRef: secondRef }))
    .rejects.toThrow(new RegExp(`/sites/site-1\\?panel=materials&workAreaId=north&assetRef=${assetRef}$`));
});
