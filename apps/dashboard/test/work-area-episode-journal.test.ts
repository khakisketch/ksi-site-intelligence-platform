import { describe, expect, it } from 'vitest';
import { readEpisodeJournal, appendEpisode, appendAttempt, settleAttempt } from '../src/app/sites/[siteId]/work-areas/work-area-episode-journal';
const identity=`v1-${'a'.repeat(64)}`;
const first={version:1 as const,siteId:'site-1',identity,body:JSON.stringify({name:'원본',polygon:{type:'Polygon',coordinates:[[[127,37],[127,38],[128,37],[127,37]]]},crs:'EPSG:4326',supersedes:null}),vertices:[{latDeg:37,lonDeg:127},{latDeg:38,lonDeg:127},{latDeg:37,lonDeg:128}],supersedesName:null};
class StorageFake { data=new Map<string,string>(); fail=false; getItem(k:string){return this.data.get(k)??null;} setItem(k:string,v:string){if(this.fail)throw Error('quota');this.data.set(k,v);} }
describe('episode journal',()=>{
 it('preserves independent episodes and attempts, including confirmed retries without resolving the first',()=>{
   const s=new StorageFake(); expect(appendEpisode(s,first,'episode_0000000001')).toBe(true);
   expect(appendAttempt(s,'site-1',identity,0,'attempt_0000000001')).toBe(true);
   expect(settleAttempt(s,'site-1',identity,0,0,{kind:'success',workAreaId:'wa',name:'원본'})).toBe(true);
   expect(appendEpisode(s,{...first,body:first.body.replace('원본','다음')},'episode_0000000002')).toBe(true);
   const r=readEpisodeJournal(s,'site-1',identity); expect(r.kind).toBe('found');
   if(r.kind==='found'){expect(r.journal.episodes).toHaveLength(2);expect(r.journal.episodes[0]!.first).toEqual(first);expect(r.journal.episodes[0]!.attempts[0]!.outcome.kind).toBe('success');}
 });
 it('does not overwrite malformed/future records or change a record on quota failure',()=>{
   const s=new StorageFake();expect(appendEpisode(s,first,'episode_0000000001')).toBe(true);
   const key=[...s.data.keys()][0]!; const raw=s.getItem(key)!; s.fail=true;
   expect(appendAttempt(s,'site-1',identity,0,'attempt_0000000001')).toBe(false); expect(s.getItem(key)).toBe(raw);
   s.fail=false; const future=JSON.stringify({...JSON.parse(raw),version:2});s.setItem(key,future);
   expect(appendEpisode(s,first,'episode_0000000001')).toBe(false);expect(s.getItem(key)).toBe(future);
 });
});
it('refuses duplicate action ids after an ambiguous readback without appending twice',()=>{
  const s=new StorageFake();
  let reads=0;const get=s.getItem.bind(s);
  s.getItem=(k:string)=>{reads++;if(reads===2)throw Error('readback');return get(k);};
  expect(appendEpisode(s,first,'episode_0000000001')).toBe(false);
  s.getItem=get;
  expect(appendEpisode(s,first,'episode_0000000001')).toBe(false);
  const journal=readEpisodeJournal(s,'site-1',identity);
  expect(journal.kind).toBe('found');
  if(journal.kind==='found') expect(journal.journal.episodes).toHaveLength(1);
});
it('rejects a reused version-2 request identity rather than merging distinct episodes',()=>{
  const s=new StorageFake();const v2={...first,version:2 as const,requestId:'12345678-1234-4123-8123-123456789012'};
  expect(appendEpisode(s,v2,'episode_0000000001')).toBe(true);
  const key=[...s.data.keys()][0]!;const before=s.getItem(key);
  expect(appendEpisode(s,{...v2,body:v2.body.replace('원본','별도')},'episode_0000000002')).toBe(false);
  expect(s.getItem(key)).toBe(before);
});
