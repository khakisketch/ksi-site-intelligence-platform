"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { StateBadge } from "@/components/ui/StatusBadge";
import { formatBytesKo, formatCountKo } from "@/lib/number-format";
import { formatKoreanDateTime } from "@/lib/datetime";

/**
 * 분리된 차분 파일 내보내기 패널이다.
 *
 * 계산 상태(AnalysisRequestPanel)와는 별개 영역이며, 페이지가 열릴 때 자동으로
 * 요청하지 않는다. 사용자가 `내보내기 준비 요청`을 눌렀을 때만 BFF를 통해
 * Core에 의도를 등록하고, 준비되면 BFF 조각들로만 파일을 조립한다.
 * 수치 결과(절토·성토·순변화)는 이 흐름과 별도로 유지되며, 내보내기 실패를
 * 수치 실패로 표현하지 않는다. TIFF 해석·격자 연산은 하지 않는다.
 */

export type DeltaPublicationSource = {
  sourceCalculationIdentityDigest: string;
  sourceNumericResultIdentityDigest: string;
  sourceCoverageWitnessDigest: string;
};

export type DeltaPublicationPanelProps = {
  /** Core 범위 — 요청·메아리 검증에 그대로 쓴다. */
  siteId: string;
  workAreaId: string;
  /** 사람용 구역 이름(표시 전용, 검증에 쓰지 않음). */
  workAreaLabel: string;
  /** Core가 확정한 세 출처 확인값 — 요청 본문의 전부다. */
  source: DeltaPublicationSource;
  /** 현장 쓰기 권한 보유 여부(부모가 Core 세션 권한에서 내려준다). */
  canRequest: boolean;
  /** 서버 발행 수명 설정(초, 부모 소유) — 지어내지 않고 그대로 보낸다. */
  lifetimeSeconds: number;
  /** 내려받기 전송 예산(바이트, 부모 소유) — 서술자 크기가 넘으면 받지 않는다. */
  downloadBudgetBytes: number;
};

/** BFF가 돌려주는 실패 모양 — Core 원문은 기술 상세로만 둔다. */
export type DeltaBffError = {
  status: number;
  code?: string;
  message: string;
  /** 알려진 종료 배치 — 폴링 중단·직행 판정에만 쓴다. */
  terminal?: "expired" | "unavailable";
};

/**
 * Core 상세 조회가 싣는 알려진 배치 코드 — `DELTA_PUBLICATION_<배치>` 닫힌 집합이다.
 * `DELTA_PUBLICATION_NOT_AVAILABLE` 같은 구형 일반형과 모르는 코드는 null로
 * 돌려 모호하게 둔다(추측 폴링 중단 금지 — 만료 시각이 폴링을 닫는다).
 */
export type DeltaKnownDisposition =
  | "NOT_YET_PUBLISHED"
  | "EXPIRED"
  | "REVOKED"
  | "CANCELED"
  | "FAILED"
  | "SOURCE_NOT_CURRENT"
  | "POLICY_NOT_CURRENT"
  | "RUNTIME_NOT_CURRENT"
  | "EGRESS_DENIED"
  | "BYTES_UNAVAILABLE"
  | "NOT_FOUND";

export function deltaDispositionFromCode(code: unknown): DeltaKnownDisposition | null {
  if (typeof code !== "string") return null;
  if (code === "DELTA_PUBLICATION_NOT_AVAILABLE") return null;
  const prefix = "DELTA_PUBLICATION_";
  if (!code.startsWith(prefix)) return null;
  const suffix = code.slice(prefix.length);
  switch (suffix) {
    case "NOT_YET_PUBLISHED":
    case "EXPIRED":
    case "REVOKED":
    case "CANCELED":
    case "FAILED":
    case "SOURCE_NOT_CURRENT":
    case "POLICY_NOT_CURRENT":
    case "RUNTIME_NOT_CURRENT":
    case "EGRESS_DENIED":
    case "BYTES_UNAVAILABLE":
    case "NOT_FOUND":
      return suffix;
    default:
      return null;
  }
}

/**
 * 종료 배치의 닫힌 사람 말 — 원문 코드는 기술 상세로만 둔다(개발자용 거대
 * 벽을 만들지 않는다). 수치 실패로는 절대 표현하지 않는다.
 */
export function deltaTerminalCopy(
  disposition: Exclude<DeltaKnownDisposition, "NOT_YET_PUBLISHED">,
): { expired: boolean; message: string } {
  switch (disposition) {
    case "EXPIRED":
      return { expired: true, message: "유효 기한이 지났습니다. 수치 결과에는 영향이 없습니다." };
    case "REVOKED":
      return { expired: false, message: "차분 파일이 회수되어 사용할 수 없습니다. 수치 결과에는 영향이 없습니다." };
    case "CANCELED":
      return { expired: false, message: "차분 파일 준비가 취소되어 사용할 수 없습니다. 수치 결과에는 영향이 없습니다." };
    case "FAILED":
      return { expired: false, message: "차분 파일 준비에 실패했습니다. 수치 결과에는 영향이 없습니다." };
    case "SOURCE_NOT_CURRENT":
      return { expired: false, message: "기준 계산·수치·범위 근거가 바뀌어 이 파일을 사용할 수 없습니다. 수치 결과에는 영향이 없습니다." };
    case "POLICY_NOT_CURRENT":
      return { expired: false, message: "발행 정책이 바뀌어 이 파일을 사용할 수 없습니다. 수치 결과에는 영향이 없습니다." };
    case "RUNTIME_NOT_CURRENT":
      return { expired: false, message: "실행 환경을 확인할 수 없어 이 파일을 사용할 수 없습니다. 수치 결과에는 영향이 없습니다." };
    case "EGRESS_DENIED":
      return { expired: false, message: "이 파일의 반출이 허용되지 않아 사용할 수 없습니다. 수치 결과에는 영향이 없습니다." };
    case "BYTES_UNAVAILABLE":
      return { expired: false, message: "파일 바이트를 확인할 수 없어 사용할 수 없습니다. 수치 결과에는 영향이 없습니다." };
    case "NOT_FOUND":
      return { expired: false, message: "차분 파일을 찾을 수 없습니다. 수치 결과에는 영향이 없습니다." };
  }
}

function readTerminal(error: unknown): { kind: "expired" | "unavailable"; code?: string; message: string } | null {
  if (error === null || typeof error !== "object") return null;
  const record = error as { terminal?: unknown; code?: unknown; message?: unknown };
  if ((record.terminal === "expired" || record.terminal === "unavailable") && typeof record.message === "string") {
    return {
      kind: record.terminal,
      code: typeof record.code === "string" ? record.code : undefined,
      message: record.message,
    };
  }
  return null;
}

export type DeltaIntentJson = {
  publicationId: string;
  siteId: string;
  workAreaId: string;
  sourceCalculationIdentityDigest: string;
  sourceNumericResultIdentityDigest: string;
  sourceCoverageWitnessDigest: string;
  outputId: string;
  status: string;
  issuedAt: string;
  expiresAt: string;
};

export type DeltaDescriptorJson = {
  publicationId: string;
  siteId: string;
  workAreaId: string;
  sourceCalculationIdentityDigest: string;
  sourceNumericResultIdentityDigest: string;
  sourceCoverageWitnessDigest: string;
  deltaSign: string;
  gridRows: number;
  gridColumns: number;
  gridCrsIdentifier: string;
  verticalUnit: string;
  dtype: string;
  outputId: string;
  outputSha256: string;
  outputSizeBytes: number;
  issuedAt: string;
  expiresAt: string;
};

export type DeltaDetailJson = {
  publicationId: string;
  siteId: string;
  workAreaId: string;
  outputId: string;
  status: string;
  issuedAt: string;
  expiresAt: string;
  descriptor: DeltaDescriptorJson;
};

export const DELTA_CHUNK_BYTES = 512 * 1024;
export const DELTA_BFF_TIMEOUT_MS = 20_000;
const BASE64_CHUNK_PATTERN = /^[A-Za-z0-9+/]*={0,2}$/;
const MAX_BASE64_LENGTH = 1_398_104;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isIntentJson(value: unknown): value is DeltaIntentJson {
  return isRecord(value)
    && isNonEmptyString(value.publicationId)
    && isNonEmptyString(value.siteId)
    && isNonEmptyString(value.workAreaId)
    && isNonEmptyString(value.outputId)
    && isNonEmptyString(value.status)
    && isNonEmptyString(value.issuedAt)
    && isNonEmptyString(value.expiresAt);
}

function isDescriptorJson(value: unknown): value is DeltaDescriptorJson {
  return isRecord(value)
    && isNonEmptyString(value.publicationId)
    && isNonEmptyString(value.outputId)
    && isNonEmptyString(value.deltaSign)
    && isPositiveInt(value.gridRows)
    && isPositiveInt(value.gridColumns)
    && isNonEmptyString(value.gridCrsIdentifier)
    && isNonEmptyString(value.verticalUnit)
    && isNonEmptyString(value.dtype)
    && isNonEmptyString(value.outputSha256)
    && isPositiveInt(value.outputSizeBytes);
}

function isDetailJson(value: unknown): value is DeltaDetailJson {
  return isRecord(value)
    && isNonEmptyString(value.publicationId)
    && isNonEmptyString(value.status)
    && isNonEmptyString(value.issuedAt)
    && isNonEmptyString(value.expiresAt)
    && isDescriptorJson(value.descriptor);
}

/** 브라우저가 받는 base64 조각의 엄격한 모양 검사 — 정규식·길이·4의 배수. */
export function isStrictBase64Chunk(value: unknown): value is string {
  if (typeof value !== "string") return false;
  if (value.length === 0 || value.length > MAX_BASE64_LENGTH) return false;
  if (value.length % 4 !== 0) return false;
  return BASE64_CHUNK_PATTERN.test(value);
}

const BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

function encodeCanonicalBase64(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i]!;
    const b = i + 1 < bytes.length ? bytes[i + 1]! : 0;
    const c = i + 2 < bytes.length ? bytes[i + 2]! : 0;
    out += BASE64_ALPHABET[a >> 2];
    out += BASE64_ALPHABET[((a & 3) << 4) | (b >> 4)];
    out += i + 1 < bytes.length ? BASE64_ALPHABET[((b & 15) << 2) | (c >> 6)] : "=";
    out += i + 2 < bytes.length ? BASE64_ALPHABET[c & 63] : "=";
  }
  return out;
}

export function decodeBase64Chunk(chunk: string): Uint8Array {
  const binary = atob(chunk);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

/** 정식 base64만 복원한다 — BFF 게이트와 같은 기준(패딩 비트 포함)이다. */
export function decodeCanonicalBase64Chunk(chunk: string): Uint8Array {
  if (!isStrictBase64Chunk(chunk)) {
    throw new Error("차분 파일 조각 형식을 확인할 수 없습니다.");
  }
  const bytes = decodeBase64Chunk(chunk);
  if (encodeCanonicalBase64(bytes) !== chunk) {
    throw new Error("차분 파일 조각 형식을 확인할 수 없습니다.");
  }
  return bytes;
}

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as unknown as BufferSource);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function bffError(status: number, value: unknown, fallback: string): DeltaBffError {
  const message = isRecord(value) && typeof value.message === "string" && value.message.length > 0
    ? value.message
    : fallback;
  const code = isRecord(value) && typeof value.code === "string" ? value.code : undefined;
  return { status, code, message };
}

async function bffJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function withTimeout(signal?: AbortSignal): { signal: AbortSignal; done: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DELTA_BFF_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  if (signal?.aborted === true) controller.abort();
  return { signal: controller.signal, done: () => { clearTimeout(timer); signal?.removeEventListener("abort", onAbort); } };
}

function intentUrl(siteId: string, workAreaId: string): string {
  return `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/delta-publications`;
}

function detailUrl(siteId: string, workAreaId: string, publicationId: string, source: DeltaPublicationSource): string {
  const query = new URLSearchParams({
    sourceCalculationIdentityDigest: source.sourceCalculationIdentityDigest,
    sourceNumericResultIdentityDigest: source.sourceNumericResultIdentityDigest,
    sourceCoverageWitnessDigest: source.sourceCoverageWitnessDigest,
  });
  return `${intentUrl(siteId, workAreaId)}/${encodeURIComponent(publicationId)}?${query.toString()}`;
}

function bytesUrl(
  siteId: string,
  workAreaId: string,
  publicationId: string,
  offset: number,
  length: number,
): string {
  const query = new URLSearchParams({ offset: String(offset), length: String(length) });
  return `${intentUrl(siteId, workAreaId)}/${encodeURIComponent(publicationId)}/bytes?${query.toString()}`;
}

/** BFF 클라이언트 API — 브라우저는 Core URL·토큰을 절대 만지지 않는다. */
export async function requestDeltaExport(
  props: Pick<DeltaPublicationPanelProps, "siteId" | "workAreaId" | "source" | "lifetimeSeconds">,
  publicationId: string,
  signal?: AbortSignal,
): Promise<DeltaIntentJson> {
  const { signal: timeoutSignal, done } = withTimeout(signal);
  try {
    const response = await fetch(intentUrl(props.siteId, props.workAreaId), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ publicationId, ...props.source, lifetimeSeconds: props.lifetimeSeconds }),
      signal: timeoutSignal,
    });
    const value = await bffJson(response);
    if (!response.ok) throw bffError(response.status, value, "차분 파일 내보내기 준비를 요청하지 못했습니다.");
    if (!isIntentJson(value)) throw { status: 502, message: "차분 파일 응답 형식을 확인할 수 없습니다." } as DeltaBffError;
    return value;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw { status: 0, message: "요청 시간이 초과되었습니다. 같은 식별자로 상태를 확인하세요." } as DeltaBffError;
    }
    throw error;
  } finally {
    done();
  }
}

export async function fetchDeltaExportDetail(
  props: Pick<DeltaPublicationPanelProps, "siteId" | "workAreaId" | "source">,
  publicationId: string,
  signal?: AbortSignal,
): Promise<DeltaDetailJson> {
  const { signal: timeoutSignal, done } = withTimeout(signal);
  try {
    const response = await fetch(detailUrl(props.siteId, props.workAreaId, publicationId, props.source), {
      signal: timeoutSignal,
    });
    const value = await bffJson(response);
    if (!response.ok) throw bffError(response.status, value, "차분 파일 상태를 확인하지 못했습니다.");
    if (!isDetailJson(value)) throw { status: 502, message: "차분 파일 응답 형식을 확인할 수 없습니다." } as DeltaBffError;
    return value;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw { status: 0, message: "상태 확인 시간이 초과되었습니다." } as DeltaBffError;
    }
    throw error;
  } finally {
    done();
  }
}

export async function fetchDeltaExportBytes(
  props: Pick<DeltaPublicationPanelProps, "siteId" | "workAreaId">,
  publicationId: string,
  offset: number,
  length: number,
  signal?: AbortSignal,
): Promise<{ publicationId: string; offset: number; contentBase64: string }> {
  const { signal: timeoutSignal, done } = withTimeout(signal);
  try {
    const response = await fetch(bytesUrl(props.siteId, props.workAreaId, publicationId, offset, length), {
      signal: timeoutSignal,
    });
    const value = await bffJson(response);
    if (!response.ok) throw bffError(response.status, value, "차분 파일 조각을 받지 못했습니다.");
    const rawChunk = isRecord(value) && typeof value.contentBase64 === "string" ? value.contentBase64 : null;
    let canonical: string | null = null;
    if (rawChunk !== null) {
      try {
        decodeCanonicalBase64Chunk(rawChunk);
        canonical = rawChunk;
      } catch {
        canonical = null;
      }
    }
    if (
      !isRecord(value)
      || value.publicationId !== publicationId
      || value.offset !== offset
      || canonical === null
    ) {
      throw { status: 502, message: "차분 파일 조각 형식을 확인할 수 없습니다." } as DeltaBffError;
    }
    return { publicationId, offset, contentBase64: canonical };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw { status: 0, message: "조각 받기 시간이 초과되었습니다." } as DeltaBffError;
    }
    throw error;
  } finally {
    done();
  }
}

type Phase = "idle" | "requesting" | "pending" | "ready" | "expired" | "unavailable" | "failed";

type DownloadState =
  | { state: "none" }
  | { state: "downloading"; loaded: number; total: number }
  | { state: "done" }
  | { state: "error"; message: string };

function createPublicationKey(): string {
  return `delta-${crypto.randomUUID()}`;
}

function requestErrorCopy(error: unknown): { message: string; technical: string | null; retryable: boolean } {
  const fallback = "차분 파일 내보내기 준비를 요청하지 못했습니다. 수치 결과에는 영향이 없습니다.";
  if (error === null || typeof error !== "object") return { message: fallback, technical: null, retryable: true };
  const record = error as { status?: unknown; code?: unknown; message?: unknown };
  const status = record.status;
  const serverMessage = typeof record.message === "string" && record.message.length > 0 ? record.message : null;
  const code = typeof record.code === "string" ? record.code : null;
  if (status === 401 || status === 403) {
    // 세션·권한 거부는 같은 요청을 다시 보내도 같은 답이다 — 자동 재시도를 봉쇄한다.
    const message = status === 401
      ? "세션이 만료되었습니다. 다시 로그인한 뒤 요청하세요. 수치 결과에는 영향이 없습니다."
      : "차분 파일 내보내기 요청 권한이 없습니다. 현장 쓰기 권한이 있는 담당자에게 요청하세요.";
    return { message, technical: code, retryable: false };
  }
  if (status === 409 || code === "DELTA_SOURCE_OR_AUTHORITY_UNAVAILABLE") {
    return { message: "기준 계산·수치·범위 근거를 현재 확인할 수 없어 내보내기를 시작하지 못했습니다. 수치 결과에는 영향이 없습니다.", technical: code ?? serverMessage, retryable: true };
  }
  if (status === 0) {
    return { message: "요청 시간이 초과되어 결과를 확인하지 못했습니다. 같은 식별자로 상태를 확인하면 중복으로 만들지 않습니다.", technical: null, retryable: true };
  }
  if (status === 503) {
    return { message: serverMessage ?? "서버가 바빠 요청을 접수하지 못했습니다. 잠시 후 같은 식별자로 다시 시도하면 중복으로 만들지 않습니다.", technical: code, retryable: true };
  }
  if (typeof status === "number" && status >= 400 && status < 500) {
    return { message: serverMessage ?? "요청 형식이 올바르지 않습니다. 입력 값을 확인하세요.", technical: code, retryable: true };
  }
  return { message: fallback, technical: code ?? serverMessage, retryable: true };
}

function signLabel(deltaSign: string): string {
  if (deltaSign === "CURRENT_MINUS_BASELINE") return "현재 − 기준";
  return deltaSign;
}

function dtypeLabel(dtype: string): string {
  if (dtype === "FLOAT64") return "FLOAT64";
  return dtype;
}

function unitLabel(unit: string): string {
  if (unit === "metre") return "미터";
  return unit;
}

export function DeltaPublicationPanel(props: DeltaPublicationPanelProps) {
  const { siteId, workAreaId, workAreaLabel, source, canRequest, lifetimeSeconds, downloadBudgetBytes } = props;
  const [phase, setPhase] = useState<Phase>("idle");
  const [intent, setIntent] = useState<DeltaIntentJson | null>(null);
  const [detail, setDetail] = useState<DeltaDetailJson | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [technicalDetail, setTechnicalDetail] = useState<string | null>(null);
  const [download, setDownload] = useState<DownloadState>({ state: "none" });
  const [retryable, setRetryable] = useState(true);
  const keyRef = useRef<string | null>(null);
  const generationRef = useRef(0);
  const mutationGenRef = useRef(0);
  const pollTimerRef = useRef<number | null>(null);
  const mutationControllersRef = useRef<Set<AbortController>>(new Set());
  const ioControllersRef = useRef<Set<AbortController>>(new Set());

  const configError = !Number.isSafeInteger(lifetimeSeconds) || lifetimeSeconds <= 0
    ? "부모 화면에서 전달된 유효 기한 설정이 올바르지 않아 요청할 수 없습니다."
    : !Number.isSafeInteger(downloadBudgetBytes) || downloadBudgetBytes <= 0
      ? "부모 화면에서 전달된 전송 예산 설정이 올바르지 않아 내려받을 수 없습니다."
      : null;

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const abortControllers = useCallback((set: Set<AbortController>) => {
    for (const controller of set) controller.abort();
    set.clear();
  }, []);

  const abortMutations = useCallback(() => {
    mutationGenRef.current += 1;
    stopPolling();
    abortControllers(mutationControllersRef.current);
  }, [stopPolling, abortControllers]);

  const abortAll = useCallback(() => {
    generationRef.current += 1;
    mutationGenRef.current += 1;
    stopPolling();
    abortControllers(mutationControllersRef.current);
    abortControllers(ioControllersRef.current);
  }, [stopPolling, abortControllers]);

  useEffect(() => () => {
    generationRef.current += 1;
    mutationGenRef.current += 1;
    if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current);
    for (const controller of mutationControllersRef.current) controller.abort();
    mutationControllersRef.current.clear();
    for (const controller of ioControllersRef.current) controller.abort();
    ioControllersRef.current.clear();
  }, []);

  /**
   * 표시 대상(현장·구역·세 출처)이 바뀌면 이전 결과를 버리고 중단한다.
   * 새 결과에 낡은 파일·주석을 보여주지 않으며, 다음 요청은 새 식별자를
   * 만든다(낡은 식별자 재사용 금지).
   */
  const identityKey = `${siteId}|${workAreaId}|${source.sourceCalculationIdentityDigest}|${source.sourceNumericResultIdentityDigest}|${source.sourceCoverageWitnessDigest}`;
  const firstIdentityRef = useRef(true);
  useEffect(() => {
    if (firstIdentityRef.current) {
      firstIdentityRef.current = false;
      return;
    }
    generationRef.current += 1;
    mutationGenRef.current += 1;
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    for (const controller of mutationControllersRef.current) controller.abort();
    mutationControllersRef.current.clear();
    for (const controller of ioControllersRef.current) controller.abort();
    ioControllersRef.current.clear();
    keyRef.current = null;
    setPhase("idle");
    setIntent(null);
    setDetail(null);
    setErrorMessage(null);
    setTechnicalDetail(null);
    setDownload({ state: "none" });
  }, [identityKey]);

  /**
   * 쓰기 권한 회수: 진행 중인 요청·확인(변이 계열)만 중단한다. 조회·내려받기는
   * Core가 별도 읽기 권한으로 판정하므로 여기서 끊지 않으며, 클라이언트
   * 게이트를 보안 경계로 약속하지 않는다.
   */
  const prevCanRequestRef = useRef(canRequest);
  useEffect(() => {
    if (prevCanRequestRef.current && !canRequest) {
      abortMutations();
      setPhase((previous) => (previous === "requesting" || previous === "pending" ? "idle" : previous));
      setErrorMessage(null);
      setTechnicalDetail(null);
    }
    prevCanRequestRef.current = canRequest;
  }, [canRequest, abortMutations]);

  const trackMutation = useCallback((controller: AbortController) => {
    mutationControllersRef.current.add(controller);
    return () => { mutationControllersRef.current.delete(controller); };
  }, []);

  const trackIo = useCallback((controller: AbortController) => {
    ioControllersRef.current.add(controller);
    return () => { ioControllersRef.current.delete(controller); };
  }, []);

  const verifyIntentEcho = useCallback((value: {
    siteId: string;
    workAreaId: string;
    publicationId: string;
    sourceCalculationIdentityDigest: string;
    sourceNumericResultIdentityDigest: string;
    sourceCoverageWitnessDigest: string;
  }, publicationId: string): boolean => {
    return value.siteId === siteId
      && value.workAreaId === workAreaId
      && value.publicationId === publicationId
      && value.sourceCalculationIdentityDigest === source.sourceCalculationIdentityDigest
      && value.sourceNumericResultIdentityDigest === source.sourceNumericResultIdentityDigest
      && value.sourceCoverageWitnessDigest === source.sourceCoverageWitnessDigest;
  }, [siteId, workAreaId, source]);

  /**
   * 상세 메아리 검증 — Core 상세(`DeltaPublicationViewV1`)는 출처 확인값을
   * 서술자 안에만 싣는다. 최상위는 범위(현장·구역·식별자)만 대조하고,
   * 출처 확인값은 서술자 메아리에서 대조한다.
   */
  const verifyDetailEcho = useCallback((value: DeltaDetailJson, publicationId: string): boolean => {
    return value.siteId === siteId
      && value.workAreaId === workAreaId
      && value.publicationId === publicationId
      && verifyIntentEcho(value.descriptor, publicationId);
  }, [siteId, workAreaId, verifyIntentEcho]);

  const checkOnce = useCallback(async (
    publicationId: string,
    generation: number,
    mutationGen: number,
  ): Promise<DeltaDetailJson | null> => {
    const controller = new AbortController();
    const untrack = trackMutation(controller);
    try {
      const fetched = await fetchDeltaExportDetail({ siteId, workAreaId, source }, publicationId, controller.signal);
      untrack();
      if (generationRef.current !== generation || mutationGenRef.current !== mutationGen) return null;
      if (!verifyDetailEcho(fetched, publicationId)) {
        throw { status: 502, message: "차분 파일 응답의 요청 범위를 확인할 수 없습니다." } as DeltaBffError;
      }
      return fetched;
    } catch (error) {
      untrack();
      if (generationRef.current !== generation || mutationGenRef.current !== mutationGen) return null;
      // 404는 모호하다 — 아직 게시 전이거나 구형 일반형이면 null로 돌려
      // 만료 시각까지만 다시 확인한다. 알려진 종료 배치는 그대로 올려
      // 폴링 없이 닫는다(추측 500 금지).
      if (error !== null && typeof error === "object" && (error as { status?: unknown }).status === 404) {
        const disposition = deltaDispositionFromCode((error as { code?: unknown }).code);
        if (disposition === null || disposition === "NOT_YET_PUBLISHED") return null;
        const copy = deltaTerminalCopy(disposition);
        throw {
          status: 404,
          code: (error as { code?: unknown }).code,
          terminal: copy.expired ? "expired" : "unavailable",
          message: copy.message,
        } as DeltaBffError;
      }
      throw error;
    }
  }, [siteId, workAreaId, source, trackMutation, verifyDetailEcho]);

  const pollStatus = useCallback((publicationId: string, generation: number, mutationGen: number, expiresAtMs: number) => {
    stopPolling();
    const tick = async () => {
      if (generationRef.current !== generation || mutationGenRef.current !== mutationGen) return;
      try {
        const fetched = await checkOnce(publicationId, generation, mutationGen);
        if (generationRef.current !== generation || mutationGenRef.current !== mutationGen) return;
        if (fetched && fetched.status === "PUBLISHED") {
          setDetail(fetched);
          setPhase("ready");
          setErrorMessage(null);
          setTechnicalDetail(null);
          return;
        }
        if (fetched) {
          setPhase("unavailable");
          setErrorMessage("차분 파일을 사용할 수 없습니다. 수치 결과에는 영향이 없습니다.");
          setTechnicalDetail(typeof fetched.status === "string" ? fetched.status : null);
          return;
        }
        if (Date.now() >= expiresAtMs) {
          setPhase("expired");
          setErrorMessage(null);
          return;
        }
        pollTimerRef.current = window.setTimeout(() => void tick(), 4000);
      } catch (error) {
        if (generationRef.current !== generation || mutationGenRef.current !== mutationGen) return;
        const terminal = readTerminal(error);
        if (terminal) {
          // 알려진 종료 — 자동 폴링을 멈추고 닫는다. 새 식별자 재요청은
          // 사용자가 명시적으로만 한다(자동 변이 재시도 금지).
          if (terminal.kind === "expired") {
            setPhase("expired");
            setErrorMessage(null);
            setTechnicalDetail(terminal.code ?? null);
          } else {
            setPhase("unavailable");
            setErrorMessage(terminal.message);
            setTechnicalDetail(terminal.code ?? null);
          }
          return;
        }
        const copy = requestErrorCopy(error);
        setPhase("failed");
        setErrorMessage(copy.message);
        setTechnicalDetail(copy.technical);
        setRetryable(copy.retryable);
      }
    };
    pollTimerRef.current = window.setTimeout(() => void tick(), 4000);
  }, [checkOnce, stopPolling]);

  /** 내보내기 준비 요청 — 같은 출처·범위 재시도는 같은 식별자를 재사용한다. */
  const requestExport = useCallback(async (options: { freshKey: boolean }) => {
    if (!canRequest || configError) return;
    abortAll();
    const generation = generationRef.current;
    const mutationGen = mutationGenRef.current;
    const publicationId = options.freshKey || !keyRef.current ? createPublicationKey() : keyRef.current!;
    keyRef.current = publicationId;
    setPhase("requesting");
    setIntent(null);
    setDetail(null);
    setErrorMessage(null);
    setTechnicalDetail(null);
    setRetryable(true);
    setDownload({ state: "none" });
    const controller = new AbortController();
    const untrack = trackMutation(controller);
    try {
      const issued = await requestDeltaExport({ siteId, workAreaId, source, lifetimeSeconds }, publicationId, controller.signal);
      untrack();
      if (generationRef.current !== generation || mutationGenRef.current !== mutationGen) return;
      if (!verifyIntentEcho(issued, publicationId)) {
        throw { status: 502, message: "차분 파일 응답의 요청 범위를 확인할 수 없습니다." } as DeltaBffError;
      }
      setIntent(issued);
      // 의도 시각은 닫힌 검증을 통과한 서버 값이다 — 파싱 실패는 추측하지 않고 실패로 닫는다.
      const expiresAtMs = Date.parse(issued.expiresAt);
      if (!Number.isFinite(expiresAtMs)) {
        throw { status: 502, message: "차분 파일 응답 형식을 확인할 수 없습니다." } as DeltaBffError;
      }
      if (issued.status === "PUBLISHED") {
        const fetched = await checkOnce(publicationId, generation, mutationGen);
        if (generationRef.current !== generation || mutationGenRef.current !== mutationGen) return;
        if (fetched && fetched.status === "PUBLISHED") {
          setDetail(fetched);
          setPhase("ready");
          return;
        }
        if (fetched) {
          // 읽힌 상세가 종료 상태면 폴링 없이 닫는다.
          if (fetched.status === "PENDING") {
            setPhase("pending");
            pollStatus(publicationId, generation, mutationGen, expiresAtMs);
            return;
          }
          if (fetched.status === "FAILED" || fetched.status === "CANCELED" || fetched.status === "REVOKED") {
            const copy = deltaTerminalCopy(fetched.status);
            setPhase("unavailable");
            setErrorMessage(copy.message);
            setTechnicalDetail(fetched.status);
            return;
          }
          throw { status: 502, message: "차분 파일 응답 형식을 확인할 수 없습니다." } as DeltaBffError;
        }
      } else if (issued.status === "FAILED" || issued.status === "CANCELED" || issued.status === "REVOKED") {
        // 멱등 POST가 기존 종료 의도를 돌려준 경우 — 자동 폴링 없이 닫는다.
        // 새 식별자 재요청은 사용자가 명시적으로만 한다.
        const copy = deltaTerminalCopy(issued.status as "FAILED" | "CANCELED" | "REVOKED");
        if (Date.now() >= expiresAtMs) {
          setPhase("expired");
          setErrorMessage(null);
          setTechnicalDetail(issued.status);
        } else {
          setPhase("unavailable");
          setErrorMessage(copy.message);
          setTechnicalDetail(issued.status);
        }
        return;
      } else if (issued.status !== "PENDING") {
        // 닫힌 의도 상태가 아니면 폴링으로 메우지 않고 실패로 닫는다.
        throw { status: 502, message: "차분 파일 응답 형식을 확인할 수 없습니다." } as DeltaBffError;
      }
      setPhase("pending");
      pollStatus(publicationId, generation, mutationGen, expiresAtMs);
    } catch (error) {
      untrack();
      if (generationRef.current !== generation || mutationGenRef.current !== mutationGen) return;
      const terminal = readTerminal(error);
      if (terminal) {
        if (terminal.kind === "expired") {
          setPhase("expired");
          setErrorMessage(null);
          setTechnicalDetail(terminal.code ?? null);
        } else {
          setPhase("unavailable");
          setErrorMessage(terminal.message);
          setTechnicalDetail(terminal.code ?? null);
        }
        return;
      }
      const copy = requestErrorCopy(error);
      setPhase("failed");
      setErrorMessage(copy.message);
      setTechnicalDetail(copy.technical);
      setRetryable(copy.retryable);
    }
  }, [canRequest, configError, abortAll, siteId, workAreaId, source, lifetimeSeconds, trackMutation, verifyIntentEcho, checkOnce, pollStatus]);

  const refreshStatus = useCallback(async () => {
    const publicationId = keyRef.current;
    if (!publicationId || phase === "requesting") return;
    const generation = generationRef.current;
    stopPolling();
    setErrorMessage(null);
    setTechnicalDetail(null);
    setRetryable(true);
    const controller = new AbortController();
    const untrack = trackIo(controller);
    try {
      const fetched = await fetchDeltaExportDetail({ siteId, workAreaId, source }, publicationId, controller.signal);
      untrack();
      if (generationRef.current !== generation) return;
      if (!verifyDetailEcho(fetched, publicationId)) {
        throw { status: 502, message: "차분 파일 응답의 요청 범위를 확인할 수 없습니다." } as DeltaBffError;
      }
      if (fetched.status === "PUBLISHED") {
        setDetail(fetched);
        setPhase("ready");
        return;
      }
      setPhase("unavailable");
      setErrorMessage("차분 파일을 사용할 수 없습니다. 수치 결과에는 영향이 없습니다.");
      setTechnicalDetail(fetched.status);
    } catch (error) {
      untrack();
      if (generationRef.current !== generation) return;
      if (error !== null && typeof error === "object" && (error as { status?: unknown }).status === 404) {
        // 알려진 종료 배치는 수동 확인에서도 폴링 없이 닫는다.
        const code = (error as { code?: unknown }).code;
        const disposition = deltaDispositionFromCode(code);
        if (disposition !== null && disposition !== "NOT_YET_PUBLISHED") {
          const copy = deltaTerminalCopy(disposition);
          if (copy.expired) {
            setPhase("expired");
            setErrorMessage(null);
            setTechnicalDetail(typeof code === "string" ? code : null);
          } else {
            setPhase("unavailable");
            setErrorMessage(copy.message);
            setTechnicalDetail(typeof code === "string" ? code : null);
          }
          return;
        }
        // 아직 게시 전이거나 구형 일반형이면 모호하다 — 유효한 만료 시각까지만
        // 다시 확인하고, 만료 시각도 없으면 추측하지 않고 닫는다.
        const expiresAtMs = intent ? Date.parse(intent.expiresAt) : Number.NaN;
        if (!Number.isFinite(expiresAtMs)) {
          setPhase("unavailable");
          setErrorMessage("차분 파일의 준비 상태를 확인할 수 없습니다. 수치 결과에는 영향이 없습니다.");
          setTechnicalDetail(null);
          return;
        }
        if (Date.now() >= expiresAtMs) {
          setPhase("expired");
          return;
        }
        setPhase("pending");
        pollStatus(publicationId, generation, mutationGenRef.current, expiresAtMs);
        return;
      }
      const copy = requestErrorCopy(error);
      setPhase("failed");
      setErrorMessage(copy.message);
      setTechnicalDetail(copy.technical);
      setRetryable(copy.retryable);
    }
  }, [phase, siteId, workAreaId, source, intent, stopPolling, trackIo, verifyDetailEcho, pollStatus]);

  const stopChecking = useCallback(() => {
    stopPolling();
    if (phase === "pending") {
      // 확인만 멈춘다 — 서버 의도를 바꾸지 않는다.
      setErrorMessage("상태 확인을 멈췄습니다. 준비된 파일은 유효 기한까지 유지됩니다.");
    }
  }, [phase, stopPolling]);

  const downloadControllerRef = useRef<AbortController | null>(null);
  const downloadCancelGenRef = useRef(-1);

  const cancelDownload = useCallback(() => {
    // 사용자 취소 표식 — 같은 세대의 타임아웃({status: 0})과 구분한다.
    downloadCancelGenRef.current = generationRef.current;
    downloadControllerRef.current?.abort();
    downloadControllerRef.current = null;
    setDownload((previous) => (previous.state === "downloading" ? { state: "none" } : previous));
  }, []);

  /**
   * 내려받기 전후로 현재 상세를 다시 확인한다. 내려받기 직전에 본 서술자는
   * 그때의 스냅샷일 뿐이므로, 실제 조각을 받기 전과 파일을 만들기 직전에
   * 같은 해시·크기·식별자·유효 기한·게시 상태를 다시 대조한다. 하나라도
   * 어긋나면(회수·만료·서술자 교체·권한 거부) 파일 없이 닫는다.
   */
  const verifyDownloadDetail = useCallback((
    fresh: DeltaDetailJson,
    shown: DeltaDescriptorJson,
    publicationId: string,
  ): { ok: true; descriptor: DeltaDescriptorJson } | { ok: false; expired: boolean; message: string } => {
    if (!verifyDetailEcho(fresh, publicationId)) {
      return { ok: false, expired: false, message: "차분 파일 응답의 요청 범위를 확인할 수 없습니다." };
    }
    const current = fresh.descriptor;
    if (fresh.status !== "PUBLISHED") {
      return { ok: false, expired: false, message: "차분 파일을 사용할 수 없습니다. 수치 결과에는 영향이 없습니다." };
    }
    if (
      current.publicationId !== shown.publicationId
      || current.outputSha256 !== shown.outputSha256
      || current.outputSizeBytes !== shown.outputSizeBytes
    ) {
      return { ok: false, expired: false, message: "파일 서술자가 바뀌었습니다. 내려받지 않습니다." };
    }
    // 최상위와 서술자의 유효 기한이 다르면 같은 발행이 아니다.
    if (fresh.expiresAt !== current.expiresAt || fresh.issuedAt !== current.issuedAt) {
      return { ok: false, expired: false, message: "파일 서술자가 바뀌었습니다. 내려받지 않습니다." };
    }
    const expiresMs = Date.parse(fresh.expiresAt);
    if (!Number.isFinite(expiresMs)) {
      return { ok: false, expired: false, message: "유효 기한을 확인할 수 없어 내려받지 않습니다." };
    }
    if (Date.now() >= expiresMs) {
      return { ok: false, expired: true, message: "유효 기한이 지났습니다. 수치 결과에는 영향이 없습니다." };
    }
    return { ok: true, descriptor: current };
  }, [verifyDetailEcho]);

  const downloadFile = useCallback(async () => {
    const publicationId = keyRef.current;
    const shown = detail?.descriptor;
    if (!publicationId || !shown || download.state === "downloading") return;
    if (shown.outputSizeBytes > downloadBudgetBytes) {
      setDownload({ state: "error", message: `파일 크기(${formatBytesKo(shown.outputSizeBytes)})가 전송 예산(${formatBytesKo(downloadBudgetBytes)})을 넘겨 내려받지 않습니다.` });
      return;
    }
    const generation = generationRef.current;
    const controller = new AbortController();
    const untrack = trackIo(controller);
    downloadControllerRef.current = controller;
    // 새 내려받기마다 취소 표식을 지운다 — 이전 취소가 이번 타임아웃을 가리면 안 된다.
    downloadCancelGenRef.current = -1;
    setDownload({ state: "downloading", loaded: 0, total: shown.outputSizeBytes });
    const stale = () => generationRef.current !== generation || controller.signal.aborted;
    const fail = (message: string, expired: boolean) => {
      untrack();
      if (downloadControllerRef.current === controller) downloadControllerRef.current = null;
      if (generationRef.current !== generation) return;
      if (expired) setPhase("expired");
      setDownload({ state: "error", message });
    };
    const readErrorMessage = (error: unknown): string | null => {
      const record = error as { status?: unknown; message?: unknown };
      if (record === null || typeof record !== "object") return null;
      if (record.status === 401) return "세션이 만료되어 내려받기를 중단했습니다. 다시 로그인하세요.";
      if (record.status === 403) return "차분 파일을 조회할 권한이 없어 내려받기를 중단했습니다. 수치 결과에는 영향이 없습니다.";
      if (typeof record.message === "string" && record.message.length > 0) return record.message;
      return null;
    };
    /**
     * 새로 확인한 메타데이터가 알려진 종료를 싣고 있으면 단계까지 내린다.
     * 준비 완료 배지·서술자·내려받기 단추를 그대로 두지 않는다 — 파일 없음은
     * 맞지만 '사용 가능' 표시는 거짓이 된다. 새 변이는 만들지 않는다.
     */
    const applyFreshTerminal = (error: unknown): boolean => {
      if (error === null || typeof error !== "object") return false;
      const record = error as { status?: unknown; code?: unknown };
      if (record.status !== 404) return false;
      const code = typeof record.code === "string" ? record.code : null;
      const disposition = deltaDispositionFromCode(record.code);
      if (disposition === null || disposition === "NOT_YET_PUBLISHED") {
        // 모호한 404 — 읽을 수 있음을 증명하지 못했으므로 파일 없이 닫고,
        // 낡은 '사용 가능' 표시도 거둔다.
        fail("차분 파일의 준비 상태를 확인할 수 없어 내려받지 않습니다. 수치 결과에는 영향이 없습니다.", false);
        if (generationRef.current !== generation) return true;
        setPhase("unavailable");
        setErrorMessage("차분 파일의 준비 상태를 확인할 수 없습니다. 수치 결과에는 영향이 없습니다.");
        setDetail(null);
        setTechnicalDetail(code);
        return true;
      }
      const copy = deltaTerminalCopy(disposition);
      fail(copy.message, copy.expired);
      if (generationRef.current !== generation) return true;
      if (copy.expired) {
        setPhase("expired");
        setErrorMessage(null);
      } else {
        setPhase("unavailable");
        setErrorMessage(copy.message);
      }
      setDetail(null);
      setTechnicalDetail(code);
      return true;
    };
    try {
      // 1) 내려받기 직전 스냅샷을 버리고 현재 상세를 다시 확인한다.
      let preChecked: DeltaDetailJson;
      try {
        preChecked = await fetchDeltaExportDetail({ siteId, workAreaId, source }, publicationId, controller.signal);
      } catch (error) {
        if (stale()) return;
        if (applyFreshTerminal(error)) return;
        throw error;
      }
      if (stale()) return;
      const pre = verifyDownloadDetail(preChecked, shown, publicationId);
      if (!pre.ok) {
        fail(pre.message, pre.expired);
        return;
      }
      if (pre.descriptor.outputSizeBytes > downloadBudgetBytes) {
        fail(`파일 크기(${formatBytesKo(pre.descriptor.outputSizeBytes)})가 전송 예산(${formatBytesKo(downloadBudgetBytes)})을 넘겨 내려받지 않습니다.`, false);
        return;
      }
      const total = pre.descriptor.outputSizeBytes;
      const expectedHash = pre.descriptor.outputSha256.startsWith("sha256:")
        ? pre.descriptor.outputSha256.slice("sha256:".length)
        : pre.descriptor.outputSha256;
      const parts: Uint8Array[] = [];
      let offset = 0;
      while (offset < total) {
        if (stale()) return;
        const length = Math.min(DELTA_CHUNK_BYTES, total - offset);
        const chunk = await fetchDeltaExportBytes({ siteId, workAreaId }, publicationId, offset, length, controller.signal);
        if (stale()) return;
        if (chunk.offset !== offset) {
          fail("조각 순서가 맞지 않아 내려받기를 중단했습니다. 파일은 만들지 않았습니다.", false);
          return;
        }
        let bytes: Uint8Array;
        try {
          bytes = decodeCanonicalBase64Chunk(chunk.contentBase64);
        } catch {
          fail("조각 형식이 맞지 않아 내려받기를 중단했습니다. 파일은 만들지 않았습니다.", false);
          return;
        }
        const isLast = offset + length >= total;
        if ((!isLast && bytes.length !== length) || (isLast && offset + bytes.length !== total)) {
          fail("조각 크기가 맞지 않아 내려받기를 중단했습니다. 파일은 만들지 않았습니다.", false);
          return;
        }
        parts.push(bytes);
        offset += bytes.length;
        if (!stale()) {
          setDownload({ state: "downloading", loaded: offset, total });
        }
      }
      const assembled = new Uint8Array(total);
      let cursor = 0;
      for (const part of parts) {
        assembled.set(part, cursor);
        cursor += part.length;
      }
      if (stale()) return;
      const actualHash = await sha256Hex(assembled);
      if (stale()) return;
      if (actualHash !== expectedHash.toLowerCase()) {
        fail("파일 확인값이 서술자와 달라 내려받기를 중단했습니다. 파일은 만들지 않았습니다.", false);
        return;
      }
      // 2) 파일을 만들기 직전, 마지막으로 현재 상세를 다시 확인한다.
      let postChecked: DeltaDetailJson;
      try {
        postChecked = await fetchDeltaExportDetail({ siteId, workAreaId, source }, publicationId, controller.signal);
      } catch (error) {
        if (stale()) return;
        if (applyFreshTerminal(error)) return;
        throw error;
      }
      if (stale()) return;
      const post = verifyDownloadDetail(postChecked, shown, publicationId);
      if (!post.ok) {
        fail(post.message, post.expired);
        return;
      }
      // 검증된 바이트만 이 지점을 통과한다 — 그 전에는 Blob·URL을 만들지 않는다.
      const blob = new Blob([assembled as unknown as BlobPart], { type: "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      untrack();
      if (downloadControllerRef.current === controller) downloadControllerRef.current = null;
      if (generationRef.current !== generation) {
        URL.revokeObjectURL(url);
        return;
      }
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `delta-${publicationId}.tiff`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      setDownload({ state: "done" });
    } catch (error) {
      if (generationRef.current !== generation) return;
      if (error instanceof DOMException && error.name === "AbortError") return;
      const record = error as { status?: unknown; message?: unknown };
      if (record !== null && typeof record === "object" && record.status === 0) {
        // 사용자 취소 표식이 있으면 조용히 닫는다. 같은 세대에서 표식 없이
        // {status: 0}이 오면 BFF 타임아웃이므로 재시도 가능한 오류로 보여준다 —
        // 'downloading' 스피너를 영원히 두지 않는다.
        if (downloadCancelGenRef.current === generation) return;
        untrack();
        if (downloadControllerRef.current === controller) downloadControllerRef.current = null;
        fail("파일 조각을 받는 데 시간이 초과되어 중단했습니다. 파일은 만들지 않았습니다. 다시 시도할 수 있습니다.", false);
        return;
      }
      untrack();
      if (downloadControllerRef.current === controller) downloadControllerRef.current = null;
      fail(readErrorMessage(error)
        ?? "파일을 내려받지 못했습니다. 수치 결과에는 영향이 없습니다.", false);
    }
  }, [detail, download.state, downloadBudgetBytes, siteId, workAreaId, source, trackIo, verifyDownloadDetail]);

  const busy = phase === "requesting" || phase === "pending" || download.state === "downloading";

  const statusBadge = phase === "ready"
    ? { label: "사용 가능", tone: "positive" as const }
    : phase === "pending" || phase === "requesting"
      ? { label: "준비 중", tone: "progress" as const }
      : phase === "expired"
        ? { label: "만료됨", tone: "warning" as const }
        : phase === "failed" || phase === "unavailable"
          ? { label: "사용 불가", tone: "warning" as const }
          : { label: "미요청", tone: "neutral" as const };

  return (
    <section aria-label="차분 파일" aria-busy={busy} className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-[14px] font-bold">차분 파일</h3>
          <p className="mt-1 text-[12px] leading-5 text-ink-2">
            {workAreaLabel} · 계산 상태와 별개인 내보내기용 결과물입니다. 형식 FLOAT64 · 현재−기준 · 미터.
          </p>
        </div>
        <StateBadge label={statusBadge.label} tone={statusBadge.tone} />
      </div>

      <p role="status" aria-live="polite" className="sr-only">
        {phase === "requesting" ? "내보내기 준비를 요청하는 중입니다."
          : phase === "pending" ? "차분 파일의 게시 여부를 확인하고 있습니다."
            : phase === "ready" ? "차분 파일을 사용할 수 있습니다."
              : phase === "expired" ? "차분 파일의 유효 기한이 지났습니다."
                : phase === "failed" || phase === "unavailable" ? (errorMessage ?? "차분 파일을 사용할 수 없습니다.")
                  : ""}
      </p>
      <div role="alert" aria-live="assertive" className="sr-only">
        {download.state === "error" ? download.message : ""}
      </div>

      <div className="border-t border-line px-4 py-3">
        {configError ? (
          <p className="rounded-md border border-crit bg-crit-bg px-3 py-2 text-[12px] leading-5 text-crit-ink">{configError}</p>
        ) : phase === "idle" ? (
          <>
            <p className="text-[12px] leading-5 text-ink-2">
              아직 내보내기를 요청하지 않았습니다. 요청하면 서버가 현재−기준 차이 격자를 별도 파일로 준비합니다.
              수치 결과는 그대로 유지됩니다.
            </p>
            {canRequest ? (
              <ResponsiveActionBoundary
                action="ANALYSIS_REQUEST"
                title="노트북에서 계속"
                reason="차분 파일 내보내기 요청은 전체 Operations Console이 필요한 운영 작업입니다."
              >
                <button
                  type="button"
                  className="btn btn-primary mt-3 min-h-11"
                  onClick={() => void requestExport({ freshKey: true })}
                >
                  내보내기 준비 요청
                </button>
              </ResponsiveActionBoundary>
            ) : (
              <div className="mt-3">
                <ActionUnavailable
                  label="내보내기 준비 요청"
                  description="차분 파일 내보내기 요청은 현장 쓰기 권한이 있는 담당자에게 요청하세요."
                />
              </div>
            )}
          </>
        ) : phase === "requesting" ? (
          <p className="text-[12px] leading-5 text-ink-2">내보내기 준비를 요청하는 중입니다. 계산 상태와 수치 결과는 바뀌지 않습니다.</p>
        ) : phase === "pending" ? (
          <>
            <p className="text-[12px] leading-5 text-ink-2">
              게시된 파일을 확인하지 못했습니다. 준비 중인지 확정할 수 없어
              {intent && <> 유효 기한 {formatKoreanDateTime(intent.expiresAt, { dateStyle: "medium", timeStyle: "short" })}까지</>} 다시 확인합니다.
              수치 결과는 그대로 유지됩니다.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className="btn min-h-11" onClick={() => void refreshStatus()}>상태 다시 확인</button>
              <button type="button" className="btn min-h-11" onClick={stopChecking}>확인 중단</button>
            </div>
            {errorMessage && <p className="mt-2 text-[12px] leading-5 text-ink-2">{errorMessage}</p>}
          </>
        ) : phase === "ready" && detail ? (
          <>
            <dl className="grid gap-2 text-[12px] text-ink-2 sm:grid-cols-2">
              <div><dt className="text-ink-muted">형식</dt><dd className="font-semibold text-ink-1">{dtypeLabel(detail.descriptor.dtype)}</dd></div>
              <div><dt className="text-ink-muted">부호</dt><dd className="font-semibold text-ink-1">{signLabel(detail.descriptor.deltaSign)}</dd></div>
              <div><dt className="text-ink-muted">단위</dt><dd className="font-semibold text-ink-1">{unitLabel(detail.descriptor.verticalUnit)}</dd></div>
              <div><dt className="text-ink-muted">격자</dt><dd className="num font-semibold text-ink-1">{formatCountKo(detail.descriptor.gridRows)}행 × {formatCountKo(detail.descriptor.gridColumns)}열</dd></div>
              <div><dt className="text-ink-muted">좌표계</dt><dd className="break-all">{detail.descriptor.gridCrsIdentifier}</dd></div>
              <div><dt className="text-ink-muted">파일 크기</dt><dd className="num">{formatBytesKo(detail.descriptor.outputSizeBytes)}</dd></div>
              <div className="sm:col-span-2"><dt className="text-ink-muted">유효 기한</dt><dd>{formatKoreanDateTime(detail.expiresAt, { dateStyle: "medium", timeStyle: "short" })}</dd></div>
            </dl>
            <details className="mt-2 text-[11.5px] text-ink-muted">
              <summary className="tap-target cursor-pointer font-semibold">출처 확인값 보기</summary>
              <dl className="mt-1 grid gap-1 break-all border-l-2 border-line pl-3">
                <div><dt>계산 신원 확인값</dt><dd>{detail.descriptor.sourceCalculationIdentityDigest}</dd></div>
                <div><dt>수치 결과 확인값</dt><dd>{detail.descriptor.sourceNumericResultIdentityDigest}</dd></div>
                <div><dt>범위 근거 확인값</dt><dd>{detail.descriptor.sourceCoverageWitnessDigest}</dd></div>
                <div><dt>파일 확인값</dt><dd>{detail.descriptor.outputSha256}</dd></div>
              </dl>
            </details>
            <p className="mt-2 text-[12px] leading-5 text-ink-muted">
              절토·성토·순변화 수치 결과는 이 파일과 별개로 유지됩니다. 내보내기 준비·실패가 수치 결과를 바꾸거나 가리지 않습니다.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-primary min-h-11"
                disabled={download.state === "downloading"}
                onClick={() => void downloadFile()}
              >
                {download.state === "downloading" ? "내려받는 중" : "차분 파일 내려받기"}
              </button>
              {download.state === "downloading" && (
                <p className="num text-[12px] text-ink-2">
                  {formatBytesKo(download.loaded)} / {formatBytesKo(download.total)}
                </p>
              )}
              {download.state === "downloading" && (
                <button type="button" className="btn min-h-11" onClick={cancelDownload}>내려받기 취소</button>
              )}
            </div>
            {download.state === "downloading" && (
              <div className="mt-2 h-1.5 overflow-hidden rounded bg-sunk" role="presentation">
                <div
                  className="h-full bg-accent"
                  style={{ width: `${download.total > 0 ? Math.min(100, (download.loaded / download.total) * 100) : 0}%` }}
                />
              </div>
            )}
            {download.state === "done" && (
              <p className="mt-2 text-[12px] leading-5 text-ink-2">내려받기 전후로 파일 정보를 대조한 뒤 내려받았습니다.</p>
            )}
            {download.state === "error" && (
              <p className="mt-2 rounded-md border border-crit bg-crit-bg px-3 py-2 text-[12px] leading-5 text-crit-ink">{download.message}</p>
            )}
          </>
        ) : phase === "expired" ? (
          <>
            <p className="text-[12px] leading-5 text-ink-2">
              준비된 파일의 유효 기한이 지났습니다. 다시 요청하면 새 식별자로 준비합니다. 수치 결과에는 영향이 없습니다.
            </p>
            {canRequest ? (
              <ResponsiveActionBoundary
                action="ANALYSIS_REQUEST"
                title="노트북에서 계속"
                reason="차분 파일 내보내기 요청은 전체 Operations Console이 필요한 운영 작업입니다."
              >
                <button
                  type="button"
                  className="btn btn-primary mt-3 min-h-11"
                  onClick={() => void requestExport({ freshKey: true })}
                >
                  다시 요청
                </button>
              </ResponsiveActionBoundary>
            ) : (
              <div className="mt-3">
                <ActionUnavailable
                  label="다시 요청"
                  description="차분 파일 내보내기 요청은 현장 쓰기 권한이 있는 담당자에게 요청하세요."
                />
              </div>
            )}
          </>
        ) : (
          <>
            <p className="text-[12px] leading-5 text-ink-2">
              {errorMessage ?? "차분 파일을 사용할 수 없습니다. 수치 결과에는 영향이 없습니다."}
            </p>
            {technicalDetail && (
              <details className="mt-2 text-[11.5px] text-ink-muted">
                <summary className="tap-target cursor-pointer font-semibold">기술 정보</summary>
                <p className="mt-1 break-all border-l-2 border-line pl-3">{technicalDetail}</p>
              </details>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              {canRequest && retryable ? (
                <ResponsiveActionBoundary
                  action="ANALYSIS_REQUEST"
                  title="노트북에서 계속"
                  reason="차분 파일 내보내기 요청은 전체 Operations Console이 필요한 운영 작업입니다."
                >
                  <button
                    type="button"
                    className="btn min-h-11"
                    onClick={() => void requestExport({ freshKey: phase === "unavailable" })}
                  >
                    {phase === "unavailable" ? "다시 요청" : "다시 시도"}
                  </button>
                </ResponsiveActionBoundary>
              ) : (
                <ActionUnavailable
                  label={phase === "unavailable" ? "다시 요청" : "다시 시도"}
                  description={canRequest
                    ? "이 오류는 같은 요청을 반복해도 해결되지 않습니다. 현장 쓰기 권한이 있는 담당자에게 확인을 요청하세요."
                    : "차분 파일 내보내기 요청은 현장 쓰기 권한이 있는 담당자에게 요청하세요."}
                />
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
