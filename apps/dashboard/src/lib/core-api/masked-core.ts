import "server-only";

import { coreApiBaseUrl } from "./env";
import { CoreApiError } from "./client";
import { getSessionToken } from "./session";

/**
 * 마스크 BFF→Core 얇은 전달 전용이다. 이 모듈은 검증하지 않는다 —
 * 검증은 호출부 BFF Route가 공용 계약(`masked-analysis.ts`)으로 먼저
 * 마치고, 여기는 토큰·경로·본문을 그대로 실어 나른다.
 *
 * 사람 OPERATOR 쓰기·읽기는 세션 토큰으로 인증한다. 종류(모바일·MCP·
 * 워커) 판정은 Core가 소유한다 — 이 BFF는 세션 유무만 보고, Core의
 * 403/404를 그대로 돌려준다(모르는·남의 기록을 구분해 알리지 않는다).
 * 객체 키·경로·URL은 Core가 절대 내놓지 않으며, 이 모듈도 로그·응답에
 * 토큰·경로를 싣지 않는다.
 */

/** BFF가 Core에서 받아들이는 JSON 응답 상한(Core `_MAX_JSON` 64KiB보다 넉넉히). */
export const MASKED_CORE_RESPONSE_JSON_BYTES = 262_144;

/** Core 업스트림 호출 제한 — 이 시간을 넘기면 호출부가 503으로 닫는다. */
export const MASKED_CORE_TIMEOUT_MS = 20_000;

function coreUrl(path: string): string {
  return new URL(path, `${coreApiBaseUrl()}/`).toString();
}

async function readBoundedText(response: Response, maxBytes: number): Promise<string> {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => undefined);
        throw new CoreApiError(502, { detail: "MASK_CORE_RESPONSE_TOO_LARGE" });
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
    || error instanceof Error && error.name === "AbortError";
}

async function withTimeout<T>(task: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), MASKED_CORE_TIMEOUT_MS);
  try {
    return await task(controller.signal);
  } catch (error) {
    if (isAbortError(error) || controller.signal.aborted) {
      throw new CoreApiError(503, { detail: "MASK_UPSTREAM_TIMED_OUT" });
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/** JSON 왕복 — Core의 상태 코드·본문을 그대로 살린다. */
export async function coreMaskJson<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const token = await getSessionToken();
  return withTimeout(async (signal) => {
    const response = await fetch(coreUrl(path), {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
      cache: "no-store",
    });
    const text = await readBoundedText(response, MASKED_CORE_RESPONSE_JSON_BYTES);
    if (!response.ok) {
      let parsed: unknown;
      try {
        parsed = text.length > 0 ? (JSON.parse(text) as unknown) : undefined;
      } catch {
        parsed = text.length > 0 ? { detail: text.slice(0, 500) } : undefined;
      }
      throw new CoreApiError(response.status, parsed);
    }
    if (text.length === 0) return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new CoreApiError(502, { detail: "MASK_CORE_RESPONSE_INVALID" });
    }
  });
}

/**
 * 원시 바이트 업로드 — `application/octet-stream` 그대로 Core에 싣는다.
 * BFF는 바이트를 해석·저장하지 않으며, 예산 초과분은 읽기 전에 끊는다.
 * 예산은 서버 설정값(`resolveMaskUploadConfig`)이며, Core 외피 상한보다
 * 클 수 없고 Core 판정이 최종이다.
 *
 * 역압력 전달: 풀당 정확히 한 청크만 읽는다. 업스트림 전체를 미리 읽어
 * 쌓지 않으며, 청크 단위로 상한을 세어 넘으면 그 즉시 끊는다. 취소·
 * 타임아웃·실패 응답은 원본 reader를 닫아 뒤에 남은 읽기를 멈춘다.
 */
export async function coreMaskUploadBytes<T>(path: string, source: {
  stream: ReadableStream<Uint8Array>;
  byteLength: number | null;
  budgetBytes: number;
}): Promise<T> {
  const token = await getSessionToken();
  return withTimeout(async (signal) => {
    const reader = source.stream.getReader();
    let total = 0;
    let finished = false;
    let released = false;
    const release = () => {
      if (!released) {
        released = true;
        try {
          reader.releaseLock();
        } catch {
          // 이미 닫혔다 — 무시한다.
        }
      }
    };
    const stopUpstream = async () => {
      try {
        await reader.cancel();
      } catch {
        // 이미 닫혔거나 취소됐다 — 무시한다.
      } finally {
        release();
      }
    };
    const onAbort = () => {
      void stopUpstream();
    };
    signal.addEventListener("abort", onAbort, { once: true });
    const bounded = new ReadableStream<Uint8Array>({
      async pull(controller) {
        if (finished) return;
        let result: ReadableStreamReadResult<Uint8Array>;
        try {
          result = await reader.read();
        } catch (error) {
          finished = true;
          release();
          controller.error(error);
          return;
        }
        if (result.done) {
          finished = true;
          release();
          if (source.byteLength !== null && total !== source.byteLength) {
            controller.error(new CoreApiError(400, { detail: "MASK_UPLOAD_SIZE_MISMATCH" }));
            return;
          }
          controller.close();
          return;
        }
        total += result.value.byteLength;
        if (total > source.budgetBytes) {
          finished = true;
          await stopUpstream();
          controller.error(new CoreApiError(413, { detail: "MASK_UPLOAD_TOO_LARGE" }));
          return;
        }
        controller.enqueue(result.value);
      },
      async cancel() {
        finished = true;
        await stopUpstream();
      },
    });
    try {
      // 길이를 미리 알면 Content-Length를 실어 Core가 먼저 거르게 한다.
      // 모르면 청크 전송으로 흘려보내고 BFF 상한으로 끊는다.
      const headers: Record<string, string> = {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/octet-stream",
      };
      if (source.byteLength !== null) headers["Content-Length"] = String(source.byteLength);
      const response = await fetch(coreUrl(path), {
        method: "POST",
        headers,
        body: bounded as unknown as BodyInit,
        signal,
        cache: "no-store",
        // Node fetch가 스트림 본문을 흘려보내도록 duplex를 명시한다.
        ...( { duplex: "half" } as Record<string, unknown> ),
      });
      const text = await readBoundedText(response, MASKED_CORE_RESPONSE_JSON_BYTES);
      if (!response.ok) {
        // 실패 응답이 오면 업스트림 읽기를 멈춘다 — 뒤 청크를 쌓지 않는다.
        await stopUpstream();
        let parsed: unknown;
        try {
          parsed = text.length > 0 ? (JSON.parse(text) as unknown) : undefined;
        } catch {
          parsed = text.length > 0 ? { detail: text.slice(0, 500) } : undefined;
        }
        throw new CoreApiError(response.status, parsed);
      }
      try {
        return JSON.parse(text) as T;
      } catch {
        throw new CoreApiError(502, { detail: "MASK_CORE_RESPONSE_INVALID" });
      }
    } finally {
      signal.removeEventListener("abort", onAbort);
    }
  });
}
