import type { SpatialAssetCatalogPage } from "@/lib/core-api/spatial-assets";
import type { ExternalArtifactKind } from "@/lib/external-reconstruction-submission";
import { SUBMISSION_REF_PATTERN } from "@/lib/external-submission-echo";

export type UploadedArtifact = {
  workAreaId: string;
  workOrderId: string;
  submissionRef: string;
  revision: number;
  artifactId: string;
  kind?: ExternalArtifactKind;
};

export function uploadedArtifactHref(siteId: string, target: UploadedArtifact): string {
  const query = new URLSearchParams({
    workAreaId: target.workAreaId, workOrderId: target.workOrderId,
    submissionRef: target.submissionRef, revision: String(target.revision), artifactId: target.artifactId,
  });
  if (target.kind && target.kind !== target.artifactId) query.set("artifactKind", target.kind);
  return `/sites/${encodeURIComponent(siteId)}/upload/open?${query}`;
}

/** 올린 직후 자료 화면이 한 번 더 읽을 수 있는 범위 — 이보다 뒤에 있으면 목록으로 보낸다. */
export const UPLOADED_ASSET_PAGE_BUDGET = 8;

const MAX_ID_LENGTH = 256;

function boundedId(raw: string | null): string | null {
  if (raw === null) return null;
  const value = raw.trim();
  return value.length > 0 && value.length <= MAX_ID_LENGTH ? value : null;
}

/** 올리기 화면이 넘긴 주소 값을 검사한다. 하나라도 틀리면 찾지 않는다. */
export function parseUploadedArtifact(query: URLSearchParams): UploadedArtifact | null {
  const workAreaId = boundedId(query.get("workAreaId"));
  const workOrderId = boundedId(query.get("workOrderId"));
  const submissionRef = query.get("submissionRef");
  const revisionText = query.get("revision");
  const artifactId = query.get("artifactId");
  const explicitKind = query.get("artifactKind");
  // Older upload links use the slot name as the identifier. A Core declaration
  // can assign a different identifier to a DSM or orthophoto.
  const kind = explicitKind ?? artifactId;
  if (!workAreaId || !workOrderId || !submissionRef || !SUBMISSION_REF_PATTERN.test(submissionRef)) return null;
  if (!revisionText || !/^[1-9][0-9]{0,15}$/.test(revisionText) || !Number.isSafeInteger(Number(revisionText))) return null;
  if (kind !== "dsm" && kind !== "ortho") return null;
  if (!artifactId || artifactId.trim() !== artifactId || [...artifactId].length > 255) return null;
  return { workAreaId, workOrderId, submissionRef, revision: Number(revisionText), artifactId, ...(explicitKind ? { kind } : {}) };
}

/**
 * Core 카탈로그를 앞에서부터 정해진 쪽 수만큼 읽어 방금 올린 파일의 자료를 찾는다.
 * 자료 참조는 Core가 만든 값만 쓴다. 찾은 쪽의 cursor를 함께 돌려줘 자료 화면이 같은 쪽을 읽게 한다.
 */
export async function locateUploadedAsset(
  siteId: string,
  target: UploadedArtifact,
  list: (cursor: string | undefined) => Promise<SpatialAssetCatalogPage>,
  pageBudget = UPLOADED_ASSET_PAGE_BUDGET,
): Promise<{ assetRef: string; cursor: string | undefined } | null> {
  let cursor: string | undefined;
  for (let read = 0; read < pageBudget; read += 1) {
    const page = await list(cursor);
    if (page.siteId !== siteId || page.workAreaId !== target.workAreaId) return null;
    const found = page.assets.find((item) => item.siteId === siteId
      && item.workAreaId === target.workAreaId
      && item.workOrderId === target.workOrderId
      && item.submissionRef === target.submissionRef
      && item.revision === target.revision
      && item.artifactId === target.artifactId && item.kind === (target.kind ?? target.artifactId));
    if (found) return { assetRef: found.assetRef, cursor };
    if (!page.hasMore || !page.nextCursor) return null;
    cursor = page.nextCursor;
  }
  return null;
}
