import type { SourceMediaFileClaim, SourceMediaItemResultView } from "./core-api/types";

// 원본 사진 업로드(M3, B1/B2) — 순수 로직과 브라우저 API 호출을 한 파일에 두되
// 경계를 분명히 나눈다. vitest 대상은 **File/Blob 같은 브라우저 전용 타입이
// 필요 없는** 함수다(vitest.config.mts: 이 프로젝트는 jsdom 을 쓰지 않는다).
// ``assignUniqueMediaIds``/``mediaIdSuffix`` 는 crypto.subtle 을 쓰지만 입력이
// 문자열이라 Node 의 표준 Web Crypto 로도 브라우저와 같은 결과가 나와 vitest
// 대상이다 — 반대로 파일 바이트·이미지 크기 측정처럼 실제 File 객체가 있어야
// 하는 부분(``sha256Hex``, ``readImageDimensions``)은 렌더 확인(390/768/1440)
// 으로만 검증한다.

// ── 순수 로직 ────────────────────────────────────────────────────────────

/**
 * 카메라 원본 파일명에서 mediaId 를 유도한다 — 규약은 **"원본 파일명 − 확장자"**다.
 *
 * ── 왜 확장자를 떼는가 ────────────────────────────────────────────────────
 * 같은 사진이 두 경로로 들어올 수 있다: 기체 컴퓨터가 자동으로 회수해 올리는 길과,
 * 사람이 SD카드를 뽑아 이 화면에서 올리는 길(ADR-KSI-013 — 자동이 주 경로, 수동은
 * 상시 보존 경로). 두 경로가 같은 사진에 **다른 mediaId** 를 붙이면 서버 번들에
 * 같은 장이 두 번 쌓이고, 그 번들의 digest 는 실제로 찍은 장수를 거짓으로 말한다.
 *
 * 자동 경로(media_offload.cpp::DeriveMediaId)는 PSDK 파일 목록에서 이름을 받는데,
 * 그 이름의 확장자 표기가 원본과 같다는 보장이 없다(대소문자·JPG/JPEG). 그래서
 * 양쪽이 **확실히 같게 만들 수 있는 부분**인 확장자 앞까지만 쓴다.
 *
 * 규칙은 아래 다섯 줄이 전부다. 규칙을 늘리면 C++ 쪽 구현과 갈릴 여지가 그만큼
 * 늘어나므로 늘리지 않는다 — 이 함수의 계약은 test/source-upload.test.ts 의
 * 골든 표이고, 자동 경로 시험이 **같은 입력 → 같은 출력**을 주장한다.
 *
 *   ① NFC 정규화 (카메라 파일명은 ASCII 라 보통 무연산이지만, 사람이 고친 이름 대비)
 *   ② 마지막 `.` 뒤를 버린다 — 단, `.` 이 첫 글자면 확장자가 아니라 이름이다
 *   ③ 허용 문자셋 밖의 연속 구간을 `-` 하나로 치환
 *   ④ 선행 비영숫자 제거 (Core 의 첫 글자 규칙)
 *   ⑤ 비면 `media`, 120자로 절단
 *
 * ④⑤ 는 Core 의 ``PATH_SAFE_IDENTIFIER_PATTERN``(``^[A-Za-z0-9][A-Za-z0-9_.-]*$``,
 * services/core/src/ksi_core/identifiers.py) 때문이다 — 서버가 다시 거부하면 등록
 * 자체가 실패하므로 클라이언트가 미리 같은 규칙을 쓴다.
 *
 * **알려진 한계**: RAW+JPEG 동시 저장(`DJI_0001.DNG` + `DJI_0001.JPG`)은 확장자를
 * 떼면 같은 mediaId 가 된다. 같은 배치 안에서는 ``assignUniqueMediaIds`` 가
 * 갈라놓지만, 다른 배치로 나뉘어 올라오면 서버가 CLAIM_CONFLICT 로 거부한다.
 * 규약이 파일명 기반인 이상 피할 수 없고, 지어낸 접미사로 덮으면 자동/수동 일치가
 * 깨진다 — 그래서 덮지 않고 서버 거부를 그대로 화면에 보여준다.
 *
 * EvidencePanel 의 ``toArtifactId`` 와 달리 타임스탬프를 붙이지 않는다 — 여기서는
 * 같은 mediaId·같은 신고값 재전송이 **의도된 멱등 재시도**다(source_media.py
 * 모듈 docstring). 매번 새 접미사를 붙이면 재시도가 항상 새 파일로 취급돼
 * 실패한 배치를 다시 올릴 때마다 중복이 쌓인다.
 */
export function deriveMediaId(fileName: string): string {
  const normalized = fileName.normalize("NFC");
  const lastDot = normalized.lastIndexOf(".");
  const stem = lastDot > 0 ? normalized.slice(0, lastDot) : normalized;
  const base = stem.replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^[^A-Za-z0-9]+/, "");
  return (base || "media").slice(0, 120);
}

// Core 의 ``PATH_SAFE_IDENTIFIER_PATTERN``(services/core/src/ksi_core/identifiers.py)
// 과 C++ 쪽 ``ArtifactVault::IsSafeArtifactId`` 가 요구하는 것과 같은 모양이다.
const CORE_IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

const MEDIA_ID_MAX_BYTES = 120;
const MEDIA_ID_SUFFIX_HEX_DIGITS = 8;

/**
 * 충돌 접미사 — 카메라 원본 파일명(확장자 포함) **문자열 자체**의 sha256 앞
 * 8 hex. 파일 바이트가 아니라 이름 문자열을 해시하는 이유는 자동 경로
 * (media_offload.cpp::MediaIdSuffix)가 PSDK 파일 목록의 이름만 갖고 있고
 * 바이트는 다운로드 전이기 때문 — 두 경로가 같은 계산을 하려면 둘 다 손에
 * 쥔 것(이름)만 써야 한다.
 */
async function mediaIdSuffix(cameraFileName: string): Promise<string> {
  const bytes = new TextEncoder().encode(cameraFileName);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest).slice(0, MEDIA_ID_SUFFIX_HEX_DIGITS / 2))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * 파일명 목록을 mediaId 로 유도하면서 같은 배치 안 충돌을 해소한다.
 *
 * 유도 규칙(``deriveMediaId``)은 다대일이라(예: `DJI_0001.JPG`, `DJI_0001.DNG`
 * 모두 `DJI_0001`) 같은 배치에 다른 파일이 같은 mediaId 로 등록되면 두 번째부터
 * CLAIM_CONFLICT 로 조용히 실패한다 — 여기서 갈라놓는다.
 *
 * 접미사는 **카메라 원본 파일명의 sha256 앞 8 hex** 다(``mediaIdSuffix``) — 선택
 * 순서에 의존하는 순번(-2, -3...) 이 아니다. 순번 방식은 같은 두 파일을 어느
 * 순서로 선택했는지에 따라 다른 mediaId 를 부여해서, 재업로드 때 선택 순서가
 * 바뀌면 같은 사진이 서버에 두 id로 쌓였다(교차 트랙 결함 — 이 함수의 원래
 * 짝인 자동 경로 ``media_offload.cpp::AssignMediaIds`` 는 처음부터 파일명
 * 해시를 썼다). 지금은 두 구현이 **같은 규칙**을 쓴다 — 짝 구현·짝 시험은
 * ``AssignMediaIds``/``media_id_assign_golden``(edge_runtime_tests.cpp) 와
 * ``MEDIA_ID_ASSIGN_GOLDEN``(source-upload.test.ts).
 *
 * 유도 후 같은 mediaId 가 되는 파일이 완전히 같은 파일명으로 두 번 이상
 * 나오면(또는 빈 파일명이면) `null` 을 돌려준다 — 해시 접미사는 이름 자체의
 * 함수라 완전히 같은 이름 두 개는 어떤 접미사를 붙여도 갈라지지 않는다. 값을
 * 지어내 진행하지 않는다(``AssignMediaIds`` 가 ``false`` 를 돌려주는 것과 같은
 * 경계).
 */
export async function assignUniqueMediaIds(fileNames: string[]): Promise<string[] | null> {
  const distinctNames = new Set<string>();
  for (const name of fileNames) {
    if (name === "" || distinctNames.has(name)) return null;
    distinctNames.add(name);
  }

  const bases = fileNames.map(deriveMediaId);
  const baseUsage = new Map<string, number>();
  for (const base of bases) {
    baseUsage.set(base, (baseUsage.get(base) ?? 0) + 1);
  }

  const room = MEDIA_ID_MAX_BYTES - (MEDIA_ID_SUFFIX_HEX_DIGITS + 1);
  const assigned = new Set<string>();
  const result: string[] = [];
  for (let i = 0; i < fileNames.length; i += 1) {
    const base = bases[i];
    let mediaId = base;
    if ((baseUsage.get(base) ?? 0) > 1) {
      const suffix = await mediaIdSuffix(fileNames[i]);
      mediaId = `${base.slice(0, Math.min(base.length, room))}-${suffix}`;
    }
    if (!CORE_IDENTIFIER_PATTERN.test(mediaId) || assigned.has(mediaId)) return null;
    assigned.add(mediaId);
    result.push(mediaId);
  }
  return result;
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
const REISSUABLE_JOB_STATUSES = new Set(["FAILED", "CANCELLED"]);

/** QUEUED/RUNNING 이면 false — 폴링을 계속해야 한다는 뜻. */
export function isTerminalJobStatus(status: string): boolean {
  return TERMINAL_JOB_STATUSES.has(status);
}

/**
 * A terminal failure may be followed by a new immutable ProcessingJob over the
 * same sealed source bundle. Successful jobs are evidence and are never
 * "retried" in place; QUEUED/RUNNING jobs must keep polling instead.
 */
export function canReissueProcessingJob(status: string | null, canIssue: boolean): boolean {
  return canIssue && status !== null && REISSUABLE_JOB_STATUSES.has(status);
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
