import type { AoiRawSnapshot } from "@/components/map/AoiPolygonMap";

export const MAP_STORAGE_KEY = "ksi-wizard-site-registration-only:map-v1";
export const DRAFT_BINDING_BACKUP_KEY = "ksi-wizard-site-registration-only:map-draft-backup";
export const MAP_BACKUP_KEY = `${MAP_STORAGE_KEY}:backup`;
const fingerprint = /^v1-[0-9a-f]{64}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export type MapRecord = { version: 1; mode: "MAPPED_BOOTSTRAP" | "LEGACY_SITE_ID"; origin: string; draftId: string; snapshot: AoiRawSnapshot };
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const keys = (v: Record<string, unknown>, names: string[]) => Object.keys(v).length === names.length && names.every((name) => Object.hasOwn(v, name));

export function parseMapRecord(raw: string): MapRecord {
  const v: unknown = JSON.parse(raw);
  if (!object(v) || !keys(v, ["version", "mode", "origin", "draftId", "snapshot"]) || v.version !== 1 || (v.mode !== "MAPPED_BOOTSTRAP" && v.mode !== "LEGACY_SITE_ID") || typeof v.origin !== "string" || !fingerprint.test(v.origin) || typeof v.draftId !== "string" || !uuid.test(v.draftId) || !object(v.snapshot) || !keys(v.snapshot, ["rows", "rejectedDraws"]) || !Array.isArray(v.snapshot.rows) || !Array.isArray(v.snapshot.rejectedDraws)) throw new Error("unsupported map record");
  if (!v.snapshot.rows.every((r: unknown) => object(r) && keys(r, ["lat", "lon"]) && typeof r.lat === "string" && typeof r.lon === "string") || !v.snapshot.rejectedDraws.every((r: unknown) => object(r) && keys(r, ["vertices", "reason"]) && typeof r.reason === "string" && Array.isArray(r.vertices) && r.vertices.every((p: unknown) => object(p) && keys(p, ["latDeg", "lonDeg"]) && typeof p.latDeg === "number" && Number.isFinite(p.latDeg) && typeof p.lonDeg === "number" && Number.isFinite(p.lonDeg)))) throw new Error("invalid map snapshot");
  return v as MapRecord;
}

export function writeMapRecord(record: MapRecord, expected: string | null): string {
  if (sessionStorage.getItem(MAP_BACKUP_KEY) !== null) throw new Error("unresolved map backup");
  const current = sessionStorage.getItem(MAP_STORAGE_KEY);
  if (current !== expected) throw new Error("map record changed");
  if (current !== null) parseMapRecord(current);
  const serialized = JSON.stringify(record);
  parseMapRecord(serialized);
  if (current !== null) {
    sessionStorage.setItem(MAP_BACKUP_KEY, current);
    if (sessionStorage.getItem(MAP_BACKUP_KEY) !== current) throw new Error("map backup not confirmed");
  }
  sessionStorage.setItem(MAP_STORAGE_KEY, serialized);
  if (sessionStorage.getItem(MAP_STORAGE_KEY) !== serialized) throw new Error("map write not confirmed");
  if (current !== null) {
    sessionStorage.removeItem(MAP_BACKUP_KEY);
    if (sessionStorage.getItem(MAP_BACKUP_KEY) !== null) throw new Error("map backup cleanup not confirmed");
  }
  return serialized;
}
