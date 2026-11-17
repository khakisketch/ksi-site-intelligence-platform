import "server-only";

import { coreFetch, coreFetchWithToken, CoreApiError } from "./client";
import {
  isDeclarationRecord,
  isDeclarationState,
  type DeclareRequestBody,
  type VerticalDeclarationRecord,
  type VerticalDeclarationState,
} from "./vertical-reference-types";

export type { VerticalDeclarationRecord, VerticalDeclarationState } from "./vertical-reference-types";

function assetPath(siteId: string, workAreaId: string, assetRef: string): string {
  return `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}`
    + `/spatial-assets/${encodeURIComponent(assetRef)}/vertical-reference`;
}

function malformed(): CoreApiError {
  return new CoreApiError(502, { verdict: "INVALID_CORE_RESPONSE" });
}

/** 한 DSM에 선언된 수직 기준의 현재 상태와 이력. 읽기만 한다. */
export async function getVerticalDeclarationState(
  siteId: string,
  workAreaId: string,
  assetRef: string,
): Promise<VerticalDeclarationState> {
  const value = await coreFetch<unknown>(assetPath(siteId, workAreaId, assetRef));
  if (!isDeclarationState(value) || value.assetRef !== assetRef) throw malformed();
  return value;
}

function unwrapWrite(value: unknown): VerticalDeclarationRecord {
  const declaration = typeof value === "object" && value !== null ? (value as Record<string, unknown>).declaration : null;
  if (!isDeclarationRecord(declaration)) throw malformed();
  return declaration;
}

/** 같은 요청 토큰으로 계정 확인과 쓰기를 잇는다. 응답은 기록 하나다. */
export async function declareVerticalReferenceWithToken(
  siteId: string,
  workAreaId: string,
  assetRef: string,
  body: DeclareRequestBody,
  idempotencyKey: string,
  token: string,
): Promise<VerticalDeclarationRecord> {
  const value = await coreFetchWithToken<unknown>(`${assetPath(siteId, workAreaId, assetRef)}/declarations`, token, {
    method: "POST",
    body,
    headers: { "Idempotency-Key": idempotencyKey },
  });
  return unwrapWrite(value);
}

export async function withdrawVerticalReferenceWithToken(
  siteId: string,
  workAreaId: string,
  assetRef: string,
  body: { expectedSequence: number },
  idempotencyKey: string,
  token: string,
): Promise<VerticalDeclarationRecord> {
  const value = await coreFetchWithToken<unknown>(`${assetPath(siteId, workAreaId, assetRef)}/withdrawals`, token, {
    method: "POST",
    body,
    headers: { "Idempotency-Key": idempotencyKey },
  });
  return unwrapWrite(value);
}
