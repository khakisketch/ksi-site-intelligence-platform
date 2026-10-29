import "server-only";

import { createHash } from "node:crypto";
import type { NextRequest } from "next/server";

import { coreFetchWithToken } from "./client";
import type { WhoAmIResponse } from "./types";

/**
 * 관측 작업 생성 재시도의 계정 연속성 검사 — usability/duplicate guard.
 *
 * Core 멱등성은 (organization_id, actor, key_hash)로 범위가 정해진다. 모호한
 * 첫 시도(A)가 실제로 접수됐는데 응답만 잃은 뒤, 같은 브라우저가 다른
 * 계정/조직(B)으로 바뀌어 같은 키를 재시도하면 Core는 두 번째 작업을 만든다.
 * 기존 UI는 이를 경고만 했고 강제하지 못했다.
 *
 * 이 모듈은 BFF가 같은 요청의 세션 토큰 하나로 현재 신원을 확인하고, 호출부가
 * 전달한 원래 신원(첫 시도 화면의 서버 파생 스냅샷)과 비교해 다르면 Core 호출
 * 없이 409로 끊는 데 쓴다. 지문은 서버가 확인한 두 식별자의 비교값일 뿐 자격
 * 증명이나 인가가 아니다. Core 권한·actor 범위 멱등 정책을 바꾸지 않는다.
 * 폼이 사라지거나 호출자가 헤더를 생략하면 중복 방지를 보장하지 않는다.
 */

export const CONTINUITY_ORG_HEADER = "x-ksi-continuity-org";
export const CONTINUITY_ACTOR_HEADER = "x-ksi-continuity-actor";
export const CONTINUITY_FINGERPRINT_HEADER = "x-ksi-continuity-fingerprint";
export const ACCOUNT_CONTINUITY_MISMATCH = "ACCOUNT_CONTINUITY_MISMATCH";

const PATH_SAFE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*(?![\s\S])/;
const FINGERPRINT_PATTERN = /^v1-[0-9a-f]{64}(?![\s\S])/;

export interface ContinuityClaim {
  organizationId: string;
  principalId: string;
}

export type ContinuityParse =
  | { status: "absent" }
  | { status: "present"; fingerprint: string }
  | { status: "present"; claim: ContinuityClaim }
  | { status: "invalid"; reason: string };

/** Core 계약의 정확한 ID를 비교한다. principal은 경로 식별자가 아닐 수 있다. */
export function continuityFingerprint(identity: unknown): string | null {
  if (!identity || typeof identity !== "object") return null;
  const { organizationId, principalId } = identity as Partial<ContinuityClaim>;
  if (typeof organizationId !== "string" || !PATH_SAFE_PATTERN.test(organizationId)
    || typeof principalId !== "string" || principalId.length === 0) return null;
  const material = JSON.stringify(["ksi-observation-continuity-v1", organizationId, principalId]);
  return `v1-${createHash("sha256").update(material, "utf8").digest("hex")}`;
}

/** 브라우저의 비교값은 신원 권한이 아니다. 기존 헤더 없는 호출도 호환한다. */
export function parseContinuityClaim(request: NextRequest): ContinuityParse {
  const org = request.headers.get(CONTINUITY_ORG_HEADER);
  const actor = request.headers.get(CONTINUITY_ACTOR_HEADER);
  const fingerprint = request.headers.get(CONTINUITY_FINGERPRINT_HEADER);
  if (fingerprint !== null) {
    if (org !== null || actor !== null || !FINGERPRINT_PATTERN.test(fingerprint)) {
      return { status: "invalid", reason: "invalid or conflicting continuity fingerprint" };
    }
    return { status: "present", fingerprint };
  }
  if (org === null && actor === null) return { status: "absent" };
  if (org === null || actor === null) {
    return { status: "invalid", reason: "continuity headers must travel as a pair" };
  }
  const orgTrimmed = org.trim();
  const actorTrimmed = actor.trim();
  if (!PATH_SAFE_PATTERN.test(orgTrimmed) || !PATH_SAFE_PATTERN.test(actorTrimmed)) {
    return { status: "invalid", reason: "continuity identity must be path-safe" };
  }
  return { status: "present", claim: { organizationId: orgTrimmed, principalId: actorTrimmed } };
}

/**
 * 같은 요청의 세션 토큰 하나로 Core whoami를 읽는다. 호출부는 이 토큰을 그대로
 * 하위 변이에도 써서 검사와 변이 사이 세션 교체(TOCTOU)를 좁힌다.
 * whoami 실패는 그대로 던져 호출부가 Core 변이 없이 끊게 한다(fail-closed).
 */
export async function fetchCurrentContinuityIdentity(token: string): Promise<ContinuityClaim> {
  const principal = await coreFetchWithToken<WhoAmIResponse>("/v1/auth/whoami", token);
  if (!continuityFingerprint(principal)) throw new Error("current continuity identity is invalid");
  return { organizationId: principal.organizationId, principalId: principal.principalId };
}

export function isSameContinuity(current: ContinuityClaim, parsed: Extract<ContinuityParse, { status: "present" }>): boolean {
  if ("fingerprint" in parsed) return continuityFingerprint(current) === parsed.fingerprint;
  return current.organizationId === parsed.claim.organizationId && current.principalId === parsed.claim.principalId;
}
