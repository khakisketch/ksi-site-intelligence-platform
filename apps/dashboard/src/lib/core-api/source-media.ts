import "server-only";

import { coreFetch } from "./client";
import type {
  SourceMediaBatchResponse,
  SourceMediaBundleView,
  SourceMediaFileClaim,
  SourceMediaSealResponse,
} from "./types";

/**
 * 원본 사진 배치 등록 — presigned PUT URL 을 받는다(B1, ADR-KSI-012/013).
 *
 * Core 는 바이트를 중계하지 않는다(ADR-KSI-010 §1) — 이 응답의 uploadUrl 로
 * 브라우저가 스토리지에 직접 PUT 한다. 배치 전체 판정과 별개로 파일 1건 단위
 * 판정(REGISTERED·CLAIM_CONFLICT 등)이 `results[]` 에 실린다 — 호출부가 항목별로
 * 갈라 처리해야 한다(upload_source_bundle.py 와 동일 관습).
 */
export async function registerSourceMedia(
  missionId: string,
  files: SourceMediaFileClaim[],
): Promise<SourceMediaBatchResponse> {
  return coreFetch<SourceMediaBatchResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/source-media`,
    { method: "POST", body: { files } },
  );
}

/** 번들 봉인 — 이후 추가 등록은 BUNDLE_SEALED 로 거부된다. */
export async function sealSourceMedia(missionId: string): Promise<SourceMediaSealResponse> {
  return coreFetch<SourceMediaSealResponse>(
    `/v1/missions/${encodeURIComponent(missionId)}/source-media/seal`,
    { method: "POST" },
  );
}

/** 현재 번들 상태 — 등록된 적 없으면 Core 가 404 를 주고 CoreApiError 로 전파된다. */
export async function getSourceMediaBundle(missionId: string): Promise<SourceMediaBundleView> {
  return coreFetch<SourceMediaBundleView>(
    `/v1/missions/${encodeURIComponent(missionId)}/source-media`,
  );
}
