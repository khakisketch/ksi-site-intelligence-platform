import { parseWorkAreaList } from "@/lib/work-areas";
import type { WorkArea } from "@/lib/core-api/types";

type Port = Pick<Storage, "getItem" | "setItem" | "key" | "length">;
export type ArchiveAttempt = { id: string; area: WorkArea; outcome: "pending" | "success" | "rejected" };
type Read = { kind: "empty" | "invalid" | "unavailable" } | { kind: "found"; journal: { attempts: ArchiveAttempt[] } };
const prefix = (site: string, identity: string) => `ksi.work-area.archive.v1:${encodeURIComponent(site)}:${identity}:`;
const object = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const keys = (v: Record<string, unknown>, expected: string[]) => Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
const validId = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v);
function validArea(area: unknown, siteId: string): area is WorkArea {
  const value = parseWorkAreaList({workAreas:[area]}, siteId)?.[0];
  return !!value && value.status === "ACTIVE" && typeof value.schemaVersion === "string" && !!value.schemaVersion;
}
/** Immutable per-attempt slots: a partial new write never overwrites any earlier attempt. */
export function readArchiveJournal(storage: Port, siteId: string, identity: string): Read {
  if (!siteId || !/^v1-[a-f0-9]{64}$/.test(identity)) return {kind:"invalid"};
  try {
    const root = prefix(siteId, identity);
    const names: string[] = [];
    for (let i = 0; i < storage.length; i++) { const name = storage.key(i); if (name?.startsWith(root)) names.push(name); }
    const ordered: Array<{sequence: number; attempt: ArchiveAttempt}> = [];
    const sequences = new Set<number>();
    const results = new Map<string, "success" | "rejected">();
    for (const name of names) {
      const suffix = name.slice(root.length);
      const result = suffix.endsWith(":result");
      const id = result ? suffix.slice(0, -7) : suffix;
      if (!validId(id)) return {kind:"invalid"};
      const raw = storage.getItem(name); if (raw === null) return {kind:"unavailable"};
      const value: unknown = JSON.parse(raw);
      if (result) {
        if (!object(value) || !keys(value,["version","siteId","identity","id","outcome"]) || value.version !== 1 || value.siteId !== siteId || value.identity !== identity || value.id !== id || (value.outcome !== "success" && value.outcome !== "rejected")) return {kind:"invalid"};
        results.set(id,value.outcome);
      } else {
        if (!object(value) || !keys(value,["version","siteId","identity","id","area","sequence"]) || value.version !== 1 || value.siteId !== siteId || value.identity !== identity || value.id !== id || !validArea(value.area,siteId) || !Number.isSafeInteger(value.sequence) || (value.sequence as number) < 1 || sequences.has(value.sequence as number)) return {kind:"invalid"};
        sequences.add(value.sequence as number);
        ordered.push({sequence: value.sequence as number, attempt:{id,area:value.area,outcome:"pending"}});
      }
    }
    const attempts = ordered.sort((a,b) => a.sequence - b.sequence).map(entry => entry.attempt);
    if (ordered.some((entry, index) => entry.sequence !== index + 1)) return {kind:"invalid"};
    if (results.size && [...results.keys()].some(id => !attempts.some(a => a.id === id))) return {kind:"invalid"};
    for (const attempt of attempts) attempt.outcome = results.get(attempt.id) ?? "pending";
    return attempts.length ? {kind:"found", journal:{attempts}} : {kind:"empty"};
  } catch (e) { return {kind:e instanceof SyntaxError ? "invalid" : "unavailable"}; }
}
export function appendArchiveAttempt(storage: Port, siteId: string, identity: string, attempt: ArchiveAttempt): boolean {
  const prior = readArchiveJournal(storage, siteId, identity);
  if (!validId(attempt.id) || attempt.outcome !== "pending" || !validArea(attempt.area,siteId) || (prior.kind !== "empty" && prior.kind !== "found")) return false;
  try {
    const name = prefix(siteId,identity) + attempt.id;
    if (storage.getItem(name) !== null || storage.getItem(name + ":result") !== null) return false;
    const sequence = prior.kind === "found" ? prior.journal.attempts.length + 1 : 1;
    const raw = JSON.stringify({version:1,siteId,identity,id:attempt.id,area:attempt.area,sequence});
    storage.setItem(name,raw);
    return storage.getItem(name) === raw;
  } catch { return false; }
}
export function settleArchiveAttempt(storage: Port, siteId: string, identity: string, id: string, outcome: "success" | "rejected"): boolean {
  const prior = readArchiveJournal(storage,siteId,identity);
  if (prior.kind !== "found" || !prior.journal.attempts.some(a => a.id === id && a.outcome === "pending")) return false;
  try {
    const name = prefix(siteId,identity) + id + ":result";
    if (storage.getItem(name) !== null) return false;
    const raw = JSON.stringify({version:1,siteId,identity,id,outcome});
    storage.setItem(name,raw);
    return storage.getItem(name) === raw;
  } catch { return false; }
}
