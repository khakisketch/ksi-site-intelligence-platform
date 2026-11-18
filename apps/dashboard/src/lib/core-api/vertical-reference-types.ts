/**
 * 수직 기준 선언 계약의 화면용 타입과 가드(`contracts/schemas/vertical-reference-declaration.v1.json`).
 * 선언은 사용자의 주장이다. 이 모양은 파일에서 확인한 값(관측)과 섞이지 않게 따로 둔다.
 * `server-only`가 아니므로 서버·클라이언트 양쪽이 import한다.
 */

import { VERTICAL_DATUMS, type VerticalDatum, ASSET_REF_PATTERN } from "./measurement-types";

export interface VerticalDeclarationRecord {
  declarationId: string;
  siteId: string;
  workAreaId: string;
  assetRef: string;
  sequence: number;
  status: "ACTIVE" | "WITHDRAWN";
  datum: VerticalDatum | null;
  unit: "metre";
  basis: string | null;
  declaredBy: string;
  declaredAt: string;
  declarationDigest: string;
}

export interface VerticalDeclarationState {
  assetRef: string;
  /** 파일이 스스로 수직 기준을 담고 있으면 true. 그때는 선언이 필요 없고 받지도 않는다. */
  observed: boolean;
  current: VerticalDeclarationRecord | null;
  history: VerticalDeclarationRecord[];
}

export const MAX_DECLARATION_BASIS = 255;

const DECLARATION_ID = /^vrd-[0-9a-f]{32}$/;
const DIGEST = /^sha256:[0-9a-f]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isDeclarationRecord(value: unknown): value is VerticalDeclarationRecord {
  if (!isRecord(value)) return false;
  if (typeof value.declarationId !== "string" || !DECLARATION_ID.test(value.declarationId)) return false;
  if (typeof value.siteId !== "string" || typeof value.workAreaId !== "string") return false;
  if (typeof value.assetRef !== "string" || !ASSET_REF_PATTERN.test(value.assetRef)) return false;
  if (!Number.isSafeInteger(value.sequence) || (value.sequence as number) < 1) return false;
  if (value.unit !== "metre") return false;
  if (typeof value.declaredBy !== "string" || typeof value.declaredAt !== "string") return false;
  if (typeof value.declarationDigest !== "string" || !DIGEST.test(value.declarationDigest)) return false;
  const datum = value.datum ?? null;
  const basis = value.basis ?? null;
  if (value.status === "ACTIVE") {
    return (VERTICAL_DATUMS as readonly unknown[]).includes(datum) && typeof basis === "string" && basis.length > 0;
  }
  // 철회 기록은 기준이나 근거를 싣지 않는다.
  return value.status === "WITHDRAWN" && datum === null && basis === null;
}

export function isDeclarationState(value: unknown): value is VerticalDeclarationState {
  if (!isRecord(value)) return false;
  if (typeof value.assetRef !== "string" || !ASSET_REF_PATTERN.test(value.assetRef)) return false;
  if (typeof value.observed !== "boolean") return false;
  if (!Array.isArray(value.history) || !value.history.every(isDeclarationRecord)) return false;
  const current = value.current ?? null;
  if (current !== null && (!isDeclarationRecord(current) || current.status !== "ACTIVE")) return false;
  // 현재 선언은 이력의 마지막 기록이어야 한다.
  const history = value.history as VerticalDeclarationRecord[];
  const last = history.length > 0 ? history[history.length - 1]! : null;
  if (current === null) return last === null || last.status === "WITHDRAWN";
  return last !== null && last.declarationId === current.declarationId;
}

export interface DeclareRequestBody {
  datum: VerticalDatum;
  unit: "metre";
  basis: string;
  expectedSequence: number;
}

/** 브라우저가 보낸 선언 본문의 형식 검사. 맞지 않으면 null이며 Core에 보내지 않는다. */
export function parseDeclareBody(value: unknown): DeclareRequestBody | null {
  if (!isRecord(value)) return null;
  const keys = Object.keys(value);
  if (keys.some((key) => !["datum", "unit", "basis", "expectedSequence"].includes(key))) return null;
  if (!(VERTICAL_DATUMS as readonly unknown[]).includes(value.datum)) return null;
  if (value.unit !== "metre") return null;
  if (typeof value.basis !== "string") return null;
  const basis = value.basis.trim();
  if (basis.length === 0 || basis.length > MAX_DECLARATION_BASIS) return null;
  if (!Number.isSafeInteger(value.expectedSequence) || (value.expectedSequence as number) < 0 || (value.expectedSequence as number) > 64) return null;
  return { datum: value.datum as VerticalDatum, unit: "metre", basis, expectedSequence: value.expectedSequence as number };
}

export function parseWithdrawBody(value: unknown): { expectedSequence: number } | null {
  if (!isRecord(value)) return null;
  if (Object.keys(value).some((key) => key !== "expectedSequence")) return null;
  const sequence = value.expectedSequence;
  if (!Number.isSafeInteger(sequence) || (sequence as number) < 1 || (sequence as number) > 64) return null;
  return { expectedSequence: sequence as number };
}
