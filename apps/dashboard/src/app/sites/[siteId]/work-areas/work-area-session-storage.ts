/** Tab-scoped transport only. Callers must independently verify the live identity and
 * validate the complete versioned payload before displaying or changing a record. */
export interface WorkAreaRecord {
  version: 1;
  siteId: string;
  identity: string;
  payload: Record<string, unknown>;
}
type StoragePort = Pick<Storage, 'getItem' | 'setItem'>;
type ReadResult =
  | { kind: 'found'; record: WorkAreaRecord }
  | { kind: 'empty' | 'invalid' | 'unavailable' | 'unverified' };
const identityPattern = /^v1-[0-9a-f]{64}$/;
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const keyFor = (siteId: string, identity: string) =>
  `ksi.work-area.v1:${encodeURIComponent(siteId)}:${identity}`;

export function readWorkAreaRecord(storage: StoragePort, siteId: string, identity: string | null): ReadResult {
  if (!identity || !identityPattern.test(identity) || !siteId) return { kind: 'unverified' };
  let raw: string | null;
  try { raw = storage.getItem(keyFor(siteId, identity)); } catch { return { kind: 'unavailable' }; }
  if (raw === null) return { kind: 'empty' };
  try {
    const value: unknown = JSON.parse(raw);
    if (!isObject(value) || !exactKeys(value, ['version', 'siteId', 'identity', 'payload']) || value.version !== 1 || value.siteId !== siteId ||
        value.identity !== identity || !isEditDraft(value.payload)) return { kind: 'invalid' };
    return { kind: 'found', record: value as unknown as WorkAreaRecord };
  } catch { return { kind: 'invalid' }; }
}

/** Never replace an unrecognised envelope. Payload validation remains the caller's
 * responsibility; do not use this transport as a complete recovery policy. */
export function writeWorkAreaRecord(storage: StoragePort, record: WorkAreaRecord): boolean {
  if (!isEditDraft(record.payload)) return false;
  const existing = readWorkAreaRecord(storage, record.siteId, record.identity);
  if (existing.kind !== 'empty' && existing.kind !== 'found') return false;
  try {
    const raw = JSON.stringify(record);
    storage.setItem(keyFor(record.siteId, record.identity), raw);
    return storage.getItem(keyFor(record.siteId, record.identity)) === raw;
  } catch { return false; }
}

import { toZonePolygon } from '@/lib/comparison-submit';
import type { AoiRawSnapshot } from '@/components/map/AoiPolygonMap';
import type { AoiVertex } from '@/lib/core-api/types';
export interface EditDraft {
  name: string;
  vertices: AoiVertex[];
  correctionId: string | null;
  correctionReady: boolean;
  snapshot: AoiRawSnapshot | null;
}
const isVertex = (v: unknown): v is AoiVertex => isObject(v) && exactKeys(v, ['latDeg', 'lonDeg']) && typeof v.latDeg === 'number' && Number.isFinite(v.latDeg) && typeof v.lonDeg === 'number' && Number.isFinite(v.lonDeg);
export function isEditDraft(value: unknown): value is EditDraft {
  if (!isObject(value) || !exactKeys(value, ['name', 'vertices', 'correctionId', 'correctionReady', 'snapshot']) || typeof value.name !== 'string' || !Array.isArray(value.vertices) || !value.vertices.every(isVertex) ||
      !(value.correctionId === null || typeof value.correctionId === 'string') || typeof value.correctionReady !== 'boolean') return false;
  if (value.snapshot === null) return true;
  const s = value.snapshot;
  return isObject(s) && exactKeys(s, ['rows', 'rejectedDraws']) && Array.isArray(s.rows) && s.rows.every((r: unknown) => isObject(r) && exactKeys(r, ['lat', 'lon']) && typeof r.lat === 'string' && typeof r.lon === 'string') &&
    Array.isArray(s.rejectedDraws) && s.rejectedDraws.every((r: unknown) => isObject(r) && exactKeys(r, ['reason', 'vertices']) && typeof r.reason === 'string' && Array.isArray(r.vertices) && r.vertices.every(isVertex));
}
export function readEditDraft(storage: StoragePort, siteId: string, identity: string | null): {kind:'found'; draft:EditDraft} | {kind:'empty'|'invalid'|'unavailable'|'unverified'} {
  const result = readWorkAreaRecord(storage, siteId, identity);
  if (result.kind !== 'found') return result;
  return isEditDraft(result.record.payload) ? {kind:'found', draft:result.record.payload} : {kind:'invalid'};
}
export function writeEditDraft(storage: StoragePort, siteId: string, identity: string, draft: EditDraft): boolean {
  if (!isEditDraft(draft)) return false;
  const existing = readEditDraft(storage, siteId, identity);
  if (existing.kind !== 'empty' && existing.kind !== 'found') return false;
  return writeWorkAreaRecord(storage, {version:1, siteId, identity, payload: draft as unknown as Record<string, unknown>});
}

/** A single first submission, separate from the editing draft. No retry is journalled here. */
export type FirstSubmission = {
  version: 1;
  requestId?: never;
  siteId: string;
  identity: string;
  body: string;
  vertices: AoiVertex[];
  supersedesName: string | null;
} | {
  version: 2;
  requestId: string;
  siteId: string;
  identity: string;
  body: string;
  vertices: AoiVertex[];
  supersedesName: string | null;
};
const submissionKey = (siteId: string, identity: string) => `ksi.work-area.first-post.v1:${encodeURIComponent(siteId)}:${identity}`;
type SubmissionStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export function validSubmission(value: unknown, siteId: string, identity: string): value is FirstSubmission {
  if (!isObject(value) || !((value.version === 1 && exactKeys(value, ['version','siteId','identity','body','vertices','supersedesName'])) ||
      (value.version === 2 && exactKeys(value, ['version','requestId','siteId','identity','body','vertices','supersedesName']) && typeof value.requestId === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value.requestId))) ||
      value.siteId !== siteId || value.identity !== identity || typeof value.body !== 'string' ||
      !Array.isArray(value.vertices) || value.vertices.length < 3 || !value.vertices.every(isVertex) ||
      !(value.supersedesName === null || typeof value.supersedesName === 'string')) return false;
  try {
    const body: unknown = JSON.parse(value.body);
    if (!isObject(body) || !exactKeys(body, ['name','polygon','crs','supersedes']) ||
        typeof body.name !== 'string' || !body.name.trim() || body.name !== body.name.trim() || body.crs !== 'EPSG:4326' ||
        !(body.supersedes === null || typeof body.supersedes === 'string')) return false;
    return JSON.stringify(body.polygon) === JSON.stringify(toZonePolygon(value.vertices));
  } catch { return false; }
}
export function readFirstSubmission(storage: SubmissionStorage, siteId: string, identity: string): {kind:'empty'|'invalid'|'unavailable'} | {kind:'found'; record:FirstSubmission; raw:string} {
  if (!siteId || !identityPattern.test(identity)) return {kind:'invalid'};
  try {
    const raw = storage.getItem(submissionKey(siteId, identity));
    if (raw === null) return {kind:'empty'};
    const record: unknown = JSON.parse(raw);
    return validSubmission(record, siteId, identity) ? {kind:'found', record, raw} : {kind:'invalid'};
  } catch (e) { return e instanceof SyntaxError ? {kind:'invalid'} : {kind:'unavailable'}; }
}
export function writeFirstSubmission(storage: SubmissionStorage, record: FirstSubmission): string | null {
  if (!validSubmission(record, record.siteId, record.identity) || readFirstSubmission(storage, record.siteId, record.identity).kind !== 'empty') return null;
  try {
    const raw = JSON.stringify(record);
    storage.setItem(submissionKey(record.siteId, record.identity), raw);
    return storage.getItem(submissionKey(record.siteId, record.identity)) === raw ? raw : null;
  } catch { return null; }
}
export function clearFirstSubmission(storage: SubmissionStorage, siteId: string, identity: string, expectedRaw: string): boolean {
  try {
    const result = readFirstSubmission(storage, siteId, identity);
    if (result.kind !== 'found' || result.raw !== expectedRaw) return false;
    storage.removeItem(submissionKey(siteId, identity));
    return storage.getItem(submissionKey(siteId, identity)) === null;
  } catch { return false; }
}

/** Returns the exact validated draft envelope, never a synthetic representation. */
export function readEditDraftRaw(storage: StoragePort, siteId:string, identity:string): string | null {
  try {
    const result=readWorkAreaRecord(storage,siteId,identity);
    if(result.kind!=='found')return null;
    const raw=storage.getItem(keyFor(siteId,identity));
    if(raw===null || JSON.stringify(JSON.parse(raw)) !== JSON.stringify(result.record))return null;
    return raw;
  } catch { return null; }
}
