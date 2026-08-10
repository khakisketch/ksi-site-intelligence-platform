import type { SourceMediaFileClaim, SourceMediaItemResultView } from "./core-api/types";

// 원본 사진 업로드(M3, B1/B2) — 순수 로직과 브라우저 API 호출을 한 파일에 두되
// 경계를 분명히 나눈다. 순수 함수만 vitest 대상이다(vitest.config.mts: 이
// 프로젝트는 jsdom 을 쓰지 않는다 — 해시·이미지 크기 측정처럼 실제 브라우저
// API 가 필요한 부분은 렌더 확인(390/768/1440)으로만 검증한다).

// ── 순수 로직 ────────────────────────────────────────────────────────────

/**
 * 파일명을 Core 의 ``PATH_SAFE_IDENTIFIER_PATTERN``(``^[A-Za-z0-9][A-Za-z0-9_.-]*$``,
 * services/core/src/ksi_core/identifiers.py)과 정확히 같은 규칙으로 정제한다 —
 * 서버가 다시 거부하면 등록 자체가 실패하므로 클라이언트가 미리 같은 규칙을 쓴다.
 *
 * EvidencePanel 의 ``toArtifactId`` 와 달리 타임스탬프를 붙이지 않는다 — 여기서는
 * 같은 mediaId·같은 신고값 재전송이 **의도된 멱등 재시도**다(source_media.py
 * 모듈 docstring). 매번 새 접미사를 붙이면 재시도가 항상 새 파일로 취급돼
 * 실패한 배치를 다시 올릴 때마다 중복이 쌓인다.
 */
export function sanitizeMediaId(fileName: string): string {
  const base = fileName
    .normalize("NFC")
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^[^A-Za-z0-9]+/, "");
  return (base || "media").slice(0, 120);
}

/**
 * 파일명 목록을 mediaId 로 정제하면서 같은 배치 안 충돌을 해소한다.
 *
 * 정제 규칙(``sanitizeMediaId``)은 다대일이라(예: `a?.jpg`, `a!.jpg` 모두
 * `a-.jpg`) 같은 배치에 다른 파일이 같은 mediaId 로 등록되면 두 번째부터
 * CLAIM_CONFLICT 로 조용히 실패한다 — 여기서 결정론적으로 갈라놓는다.
 */
export function assignUniqueMediaIds(fileNames: string[]): string[] {
  const seen = new Map<string, number>();
  return fileNames.map((name) => {
    const base = sanitizeMediaId(name);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    if (count === 0) return base;
    // 뒤에 붙는 카운터도 identifier 패턴을 유지한다(숫자+`-` 는 이미 허용 문자셋).
    return `${base}-${count + 1}`;
  });
}

/** 배열을 최대 size 크기 묶음으로 나눈다(서버 배치 상한 MAX_BATCH_SIZE=200 대응). */
export function chunk<T>(items: readonly T[], size: number): T[][] {
  const result: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    result.push(items.slice(i, i + size));
  }
  return result;
}

export interface UploadBatchSummary {
  /** 업로드를 진행할 수 있는 항목 — REGISTERED + uploadUrl 확보. */
  ready: Array<{ mediaId: string; uploadUrl: string }>;
  /** 등록 자체가 실패한 항목 — 업로드를 시도하지 않는다. */
  failed: Array<{ mediaId: string; verdict: string; detail: string | null }>;
}

/**
 * 배치 등록 응답을 "업로드 가능"과 "등록 실패"로 가른다.
 *
 * ``REGISTERED`` 라도 presigned URL 발급이 실패하면(``STORAGE_UNAVAILABLE``)
 * 서버가 verdict 를 그렇게 격하해 돌려준다 — uploadUrl 유무가 아니라 verdict
 * 자체로 판정한다(item.upload_url 이 null 인데 verdict 는 REGISTERED 인 경우는
 * 계약상 없다).
 */
export function summarizeUploadBatch(results: readonly SourceMediaItemResultView[]): UploadBatchSummary {
  const ready: UploadBatchSummary["ready"] = [];
  const failed: UploadBatchSummary["failed"] = [];
  for (const item of results) {
    if (item.verdict === "REGISTERED" && item.uploadUrl) {
      ready.push({ mediaId: item.mediaId, uploadUrl: item.uploadUrl });
    } else {
      failed.push({ mediaId: item.mediaId, verdict: item.verdict, detail: item.detail });
    }
  }
  return { ready, failed };
}

const TERMINAL_JOB_STATUSES = new Set(["SUCCEEDED", "FAILED", "CANCELLED"]);

/** QUEUED/RUNNING 이면 false — 폴링을 계속해야 한다는 뜻. */
export function isTerminalJobStatus(status: string): boolean {
  return TERMINAL_JOB_STATUSES.has(status);
}

// ── 브라우저 API 호출(순수 로직 아님 — vitest 대상 아님) ────────────────────

async function sha256Hex(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function readImageDimensions(file: File): Promise<{ width: number; height: number }> {
  const bitmap = await createImageBitmap(file);
  try {
    return { width: bitmap.width, height: bitmap.height };
  } finally {
    bitmap.close();
  }
}

/** 파일 1건을 등록 신고값으로 변환한다 — 전 바이트를 읽어 sha256 을 계산한다. */
export async function buildSourceMediaClaim(
  file: File,
  mediaId: string,
): Promise<SourceMediaFileClaim> {
  const [sha256, { width, height }] = await Promise.all([
    sha256Hex(file),
    readImageDimensions(file),
  ]);
  return {
    mediaId,
    sha256,
    bytes: file.size,
    width,
    height,
    contentType: file.type || "application/octet-stream",
  };
}
