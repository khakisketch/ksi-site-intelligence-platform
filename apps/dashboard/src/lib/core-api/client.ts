import "server-only";

import { coreApiBaseUrl } from "./env";
import { getSessionToken } from "./session";

function extractDetailText(raw: unknown): string | undefined {
  if (typeof raw === "string") return raw;
  // FastAPI 요청검증 422 는 detail 이 {loc,msg,type} 배열이다 — 합쳐서 사람이 읽을 문장으로.
  if (Array.isArray(raw)) {
    const messages = raw
      .map((item) =>
        item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : undefined,
      )
      .filter((m): m is string => Boolean(m));
    return messages.length ? messages.join(" / ") : undefined;
  }
  return undefined;
}

// Site/Event API 는 {verdict, detail} 을 함께 반환하지만, Mission Records/Plans API
// (services/core/src/ksi_core/mission_records.py raise_for_mission_record_verdict,
// mission_plans.py RouteGenerationError)는 verdict 필드 없이 detail 하나에만 코드를
// 싣는다 — 셋 중 하나 형태다: "CODE"(단독) / "CODE — 설명" / "CODE: 설명". 독립
// 재검토 P1-D(2차) — 이 세 패턴만 좁게 매칭해 문장 중간에 등장하는 대문자 값
// (예: "AUTONOMOUS_PATROL 는 lawnmower 패턴 — ...")을 코드로 오인하지 않는다.
function extractCodeFromDetail(text: string): { code: string; message: string | undefined } | undefined {
  const bare = /^([A-Z][A-Z0-9_]{2,})$/.exec(text);
  if (bare) return { code: bare[1], message: undefined };
  const dashed = /^([A-Z][A-Z0-9_]{2,}) — ([\s\S]*)$/.exec(text);
  if (dashed) return { code: dashed[1], message: dashed[2].trim() || undefined };
  const coloned = /^([A-Z][A-Z0-9_]{2,}): ([\s\S]*)$/.exec(text);
  if (coloned) return { code: coloned[1], message: coloned[2].trim() || undefined };
  return undefined;
}

export class CoreApiError extends Error {
  readonly status: number;
  /** 서버 verdict 코드(예: EMPTY_ALLOWED_VOLUMES) — API_ERROR_MESSAGE 조회 키. */
  readonly code: string | undefined;
  /** 서버가 준 구체 설명 문장 — code 로 못 찾을 때의 최후 대체 표시용(§3.4). */
  readonly serverMessage: string | undefined;
  /** `RESOURCE_LIMIT_EXCEEDED` 아래의 안정된 하위 사유. 화면은 이 값으로만 다음 행동을 고른다. */
  readonly reasonCode: string | undefined;

  /** 서버 Retry-After 헤더(초). 503 이 "언제 돌아오는지"를 말해줬다면 그 값이다.
   *
   *  ErrorState 는 이 값으로 카운트다운을 그리는 UI 를 이미 갖고 있었는데, 정작
   *  이 에러가 헤더를 캡처하지 않아 **소스가 없는 죽은 prop** 이었다(2026-08-18
   *  states 규격 정비에서 확인). 선택 필드라 기존 catch 경로는 그대로 동작한다. */
  readonly retryAfterSeconds: number | undefined;

  constructor(status: number, body: unknown, retryAfterSeconds?: number) {
    const parsed = (body ?? {}) as Record<string, unknown>;
    const bodyVerdict = typeof parsed.verdict === "string" ? parsed.verdict : undefined;
    const bodyReasonCode = typeof parsed.reasonCode === "string" ? parsed.reasonCode : undefined;
    const detailText = extractDetailText(parsed.detail);

    let code = bodyVerdict;
    let serverMessage = detailText;
    if (!code && detailText) {
      const extracted = extractCodeFromDetail(detailText);
      if (extracted) {
        code = extracted.code;
        serverMessage = extracted.message;
      }
    }
    // SpatialDataErrorV1 uses `reason`, not `verdict`. Preserve only its typed
    // refusal envelope; arbitrary `reason` prose must not become a decision code.
    if (!code && typeof parsed.reason === "string" && /^[A-Z][A-Z0-9_]{2,127}$/.test(parsed.reason)
      && typeof parsed.message === "string" && typeof parsed.retryable === "boolean"
      && Array.isArray(parsed.remediation) && parsed.remediation.length >= 1 && parsed.remediation.length <= 16
      && parsed.remediation.every((item) => typeof item === "string" && /^[A-Z][A-Z0-9_]{2,63}$/.test(item))) {
      code = parsed.reason;
    }

    super(`Core API ${status}: ${code ?? serverMessage ?? "unknown error"}`);
    this.status = status;
    this.code = code;
    this.serverMessage = serverMessage;
    this.reasonCode = bodyReasonCode;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** Retry-After 헤더 파싱 — 초 단위 정수만 받는다(HTTP-date 형태는 쓰지 않으므로 무시). */
function parseRetryAfter(response: Response): number | undefined {
  const raw = response.headers.get("retry-after");
  if (!raw) return undefined;
  const seconds = Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

export interface CoreFetchOptions {
  method?: "GET" | "POST" | "PUT";
  query?: Record<string, string | number | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
}

function buildUrl(path: string, query?: CoreFetchOptions["query"]): string {
  const url = new URL(path, coreApiBaseUrl() + "/");
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** 응답까지만 받고 본문 해석은 호출부(JSON/바이너리)에 맡긴다 — !ok 는 여기서 공통 처리. */
async function rawCoreRequest(
  path: string,
  token: string,
  options: CoreFetchOptions = {},
): Promise<Response> {
  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    // 이 대시보드는 Next 데이터 캐시에 기대지 않는다 — 매 요청 Core API 최신 상태를 그대로
    // 반영한다(운영자가 현장/이벤트/임무 최신 상태를 봐야 하므로 staleness 허용치가 낮다).
    cache: "no-store",
  });

  if (!response.ok) {
    const isJson = response.headers.get("content-type")?.includes("application/json");
    const body = isJson ? await response.json() : undefined;
    throw new CoreApiError(response.status, body, parseRetryAfter(response));
  }
  return response;
}

async function rawCoreFetch<T>(
  path: string,
  token: string,
  options: CoreFetchOptions = {},
): Promise<T> {
  const response = await rawCoreRequest(path, token, options);
  const isJson = response.headers.get("content-type")?.includes("application/json");
  return (isJson ? await response.json() : undefined) as T;
}

/** 로그인 화면에서 사용자가 입력한 토큰을 검증할 때만 쓴다 — 세션 쿠키에 의존하지 않는다. */
export async function coreFetchWithToken<T>(
  path: string,
  token: string,
  options: CoreFetchOptions = {},
): Promise<T> {
  return rawCoreFetch<T>(path, token, options);
}

/** 앱 전역 기본 진입점 — 로그인한 운영자의 세션 토큰을 자동으로 싣는다(§session.ts). */
export async function coreFetch<T>(path: string, options: CoreFetchOptions = {}): Promise<T> {
  const token = await getSessionToken();
  return rawCoreFetch<T>(path, token, options);
}

export interface CoreBinaryResponse {
  body: ArrayBuffer;
  contentType: string;
  /** 원본 그대로 전달한다 — 파일명 파싱은 호출부가 이미 아는 값(예: missionId)으로 대신한다. */
  contentDisposition: string | null;
}

/**
 * KMZ 같은 바이너리 산출물 조회 전용 — JSON 파싱 없이 원본 바이트를 그대로 넘긴다.
 * 세션 토큰을 자동으로 싣는다(``coreFetch`` 와 동일 관습, GET 전용이라 body 는 없다).
 */
export async function coreFetchBinary(path: string): Promise<CoreBinaryResponse> {
  const token = await getSessionToken();
  const response = await rawCoreRequest(path, token);
  return {
    body: await response.arrayBuffer(),
    contentType: response.headers.get("content-type") ?? "application/octet-stream",
    contentDisposition: response.headers.get("content-disposition"),
  };
}
