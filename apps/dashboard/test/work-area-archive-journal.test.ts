import { describe, expect, it } from "vitest";
import { appendArchiveAttempt, readArchiveJournal, settleArchiveAttempt } from "@/app/sites/[siteId]/work-areas/work-area-archive-journal";
import type { WorkArea } from "@/lib/core-api/types";
const identity = `v1-${"a".repeat(64)}`;
const one = "11111111-1111-4111-8111-111111111111";
const two = "22222222-2222-4222-8222-222222222222";
const area: WorkArea = {schemaVersion:"1.0",siteId:"site-1",workAreaId:"area-1",name:"구역",polygon:{type:"Polygon",coordinates:[[[0,0],[1,0],[1,1],[0,0]]]},crs:"EPSG:4326",status:"ACTIVE",supersedes:null,createdAt:"2026-01-01"};
function storage() {
  const map = new Map<string,string>();
  return {map, get length(){return map.size;}, key(i:number){return [...map.keys()][i] ?? null;}, getItem(k:string){return map.get(k) ?? null;}, setItem(k:string,v:string){map.set(k,v);}};
}
describe("archive journal immutable slots", () => {
  it("keeps the first pending attempt when a separate attempt is rejected and detects id collision", () => {
    const s=storage();
    expect(appendArchiveAttempt(s,"site-1",identity,{id:one,area,outcome:"pending"})).toBe(true);
    expect(appendArchiveAttempt(s,"site-1",identity,{id:one,area,outcome:"pending"})).toBe(false);
    expect(appendArchiveAttempt(s,"site-1",identity,{id:two,area,outcome:"pending"})).toBe(true);
    expect(settleArchiveAttempt(s,"site-1",identity,two,"rejected")).toBe(true);
    const result=readArchiveJournal(s,"site-1",identity);
    expect(result.kind).toBe("found");
    if (result.kind === "found") expect(result.journal.attempts.map(a=>a.outcome)).toEqual(["pending","rejected"]);
  });
  it("preserves original bytes and fails closed on a partial later write", () => {
    const s=storage();
    expect(appendArchiveAttempt(s,"site-1",identity,{id:one,area,outcome:"pending"})).toBe(true);
    const original=[...s.map.entries()][0]!;
    const bad={...s, get length(){return s.length;}, setItem(k:string){s.map.set(k,"{");}};
    expect(appendArchiveAttempt(bad,"site-1",identity,{id:two,area,outcome:"pending"})).toBe(false);
    expect(s.map.get(original[0])).toBe(original[1]);
    expect(readArchiveJournal(s,"site-1",identity).kind).toBe("invalid");
    expect(appendArchiveAttempt(s,"site-1",identity,{id:two,area,outcome:"pending"})).toBe(false);
  });
});
