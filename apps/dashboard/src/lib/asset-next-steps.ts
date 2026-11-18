/** 검사를 마친 자료에서 이어서 할 수 있는 일. 파일 정보가 확인된 자료에만 보인다. 분석 가능 여부는 말하지 않는다. */

export type AssetNextStep = { key: "viewer" | "measurements"; label: string; href: string };

export function assetNextSteps(asset: {
  siteId: string;
  workAreaId: string;
  kind: string;
  lifecycleState: string;
  inspection: { outcome: string | null; state: string };
}): AssetNextStep[] {
  const measured = asset.inspection.outcome === "MEASURED"
    && asset.inspection.state !== "FAILED"
    && asset.lifecycleState !== "UNSEALED"
    && asset.lifecycleState !== "SUPERSEDED";
  if (!measured) return [];
  const site = `/sites/${encodeURIComponent(asset.siteId)}`;
  const area = encodeURIComponent(asset.workAreaId);
  const steps: AssetNextStep[] = [{ key: "viewer", label: "공간에서 보기", href: `${site}?workAreaId=${area}` }];
  if (asset.kind === "dsm") steps.push({ key: "measurements", label: "측정 선에서 단면 읽기", href: `${site}/measurements?workAreaId=${area}` });
  return steps;
}
