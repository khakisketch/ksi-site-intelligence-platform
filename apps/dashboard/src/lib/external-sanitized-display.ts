import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

/** Display-only client cap. It does not change Core's external validation policy or source artifact limits. */
export const EXTERNAL_SANITIZED_DISPLAY_MAX_BYTES = 64 * 1024 * 1024;

const digestPattern = /^sha256:[0-9a-f]{64}$/;
const displayRefPattern = /^sda-v1-[A-Za-z0-9][A-Za-z0-9_-]{0,247}$/;
const forbiddenHeaderNames = new Set(["authorization", "cookie", "proxy-authorization"]);

export type ExternalSanitizedDisplayCapability = {
  sanitizedDisplayRef: string;
  receiptDigest: string;
  observedDerivativeSha256: string;
  observedDerivativeSizeBytes: number;
  observedDerivativeContentType: string;
  downloadUrl: string;
  expiresAt: string;
  requiredHeaders: Record<string, string>;
};

function fail(message: string): never { throw new Error(message); }

function safeCapabilityUrl(value: string): URL {
  let url: URL;
  try { url = new URL(value); } catch { return fail("정제 표시 권한 주소가 안전하지 않습니다."); }
  if ((url.protocol !== "https:" && url.protocol !== "http:") || url.username || url.password) {
    return fail("정제 표시 권한 주소가 안전하지 않습니다.");
  }
  return url;
}

function safeHeaders(value: Record<string, string>): Headers {
  const headers = new Headers();
  for (const [name, headerValue] of Object.entries(value)) {
    if (!/^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$/.test(name) || typeof headerValue !== "string" || headerValue.length > 1024 || /[\r\n]/.test(headerValue) || forbiddenHeaderNames.has(name.toLowerCase())) {
      return fail("정제 표시 권한 헤더가 안전하지 않습니다.");
    }
    headers.set(name, headerValue);
  }
  return headers;
}

function abortSignalFrom(externalSignal?: AbortSignal): { controller: AbortController; detach: () => void } {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (externalSignal?.aborted) abort();
  else externalSignal?.addEventListener("abort", abort, { once: true });
  return {
    controller,
    detach: () => externalSignal?.removeEventListener("abort", abort),
  };
}

function cancelWithoutAwait(cancel: () => Promise<unknown>): void {
  try { void cancel().catch(() => undefined); } catch { /* preserve the primary safe rejection */ }
}

function rejectResponse(response: Response, controller: AbortController, message: string): never {
  controller.abort();
  if (response.body) cancelWithoutAwait(() => response.body!.cancel());
  return fail(message);
}

export function isExternalSanitizedDisplayCapability(value: unknown): value is ExternalSanitizedDisplayCapability {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.sanitizedDisplayRef === "string" && typeof candidate.receiptDigest === "string" &&
    typeof candidate.observedDerivativeSha256 === "string" && typeof candidate.observedDerivativeSizeBytes === "number" &&
    typeof candidate.observedDerivativeContentType === "string" && typeof candidate.downloadUrl === "string" &&
    typeof candidate.expiresAt === "string" && !!candidate.requiredHeaders && typeof candidate.requiredHeaders === "object" && !Array.isArray(candidate.requiredHeaders);
}

function validateCapability(capability: ExternalSanitizedDisplayCapability): { url: URL; headers: Headers } {
  if (!displayRefPattern.test(capability.sanitizedDisplayRef) || !digestPattern.test(capability.receiptDigest) || !digestPattern.test(capability.observedDerivativeSha256)) {
    return fail("정제 표시 권한의 식별 정보가 올바르지 않습니다.");
  }
  if (!Number.isSafeInteger(capability.observedDerivativeSizeBytes) || capability.observedDerivativeSizeBytes < 1 || capability.observedDerivativeSizeBytes > EXTERNAL_SANITIZED_DISPLAY_MAX_BYTES) {
    return fail("정제 표시 파일 크기가 브라우저 표시 한계를 벗어났습니다.");
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}$/.test(capability.observedDerivativeContentType)) {
    return fail("정제 표시 파일 형식이 올바르지 않습니다.");
  }
  const expiresAt = Date.parse(capability.expiresAt);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) return fail("정제 표시 권한이 만료되었습니다. 상태를 새로고침하세요.");
  return { url: safeCapabilityUrl(capability.downloadUrl), headers: safeHeaders(capability.requiredHeaders) };
}

/**
 * Fetches only a current Core-issued sanitized derivative. The bytes remain unavailable to
 * GeoTIFF parsing until the declared size, MIME type, and digest all match exactly.
 */
export async function fetchVerifiedSanitizedDisplay(capability: ExternalSanitizedDisplayCapability, signal?: AbortSignal): Promise<ArrayBuffer> {
  const { url, headers } = validateCapability(capability);
  const { controller, detach } = abortSignalFrom(signal);
  try {
    const response = await fetch(url, { method: "GET", headers, credentials: "omit", redirect: "error", referrerPolicy: "no-referrer", signal: controller.signal });
    if (response.redirected || response.type === "opaqueredirect") return rejectResponse(response, controller, "정제 표시 다운로드 리디렉션을 거부했습니다.");
    if (!response.ok) return rejectResponse(response, controller, `정제 표시 다운로드에 실패했습니다(HTTP ${response.status}).`);
    const contentType = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
    if (contentType !== capability.observedDerivativeContentType.toLowerCase()) return rejectResponse(response, controller, "정제 표시 파일 형식이 Core 관측값과 다릅니다.");
    if (!response.body) return rejectResponse(response, controller, "정제 표시 바이트를 받을 수 없습니다.");

    const reader = response.body.getReader();
    const cancelReader = () => cancelWithoutAwait(() => reader.cancel());
    const chunks: Uint8Array[] = [];
    const hasher = sha256.create();
    let total = 0;
    let complete = false;
    controller.signal.addEventListener("abort", cancelReader, { once: true });
    try {
      while (true) {
        if (controller.signal.aborted) return fail("정제 표시 다운로드를 취소했습니다.");
        let result: ReadableStreamReadResult<Uint8Array>;
        try { result = await reader.read(); }
        catch {
          return fail(controller.signal.aborted ? "정제 표시 다운로드를 취소했습니다." : "정제 표시 바이트를 읽을 수 없습니다.");
        }
        if (controller.signal.aborted) return fail("정제 표시 다운로드를 취소했습니다.");
        if (result.done) {
          complete = true;
          break;
        }
        total += result.value.byteLength;
        if (total > capability.observedDerivativeSizeBytes || total > EXTERNAL_SANITIZED_DISPLAY_MAX_BYTES) return fail("정제 표시 바이트 크기가 Core 관측값과 다릅니다.");
        chunks.push(result.value);
        hasher.update(result.value);
      }
    } finally {
      controller.signal.removeEventListener("abort", cancelReader);
      if (!complete) {
        controller.abort();
        cancelReader();
      }
      reader.releaseLock();
    }
    if (total !== capability.observedDerivativeSizeBytes) return fail("정제 표시 바이트 크기가 Core 관측값과 다릅니다.");
    if (`sha256:${bytesToHex(hasher.digest())}` !== capability.observedDerivativeSha256) return fail("정제 표시 바이트 해시가 Core 관측값과 다릅니다.");
    const result = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
    return result.buffer;
  } finally {
    detach();
  }
}
