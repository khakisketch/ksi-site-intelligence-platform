import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils.js';
/** Tab-scoped episode journal. Callers verify live identity before using it. */
import { validSubmission, isEditDraft, type FirstSubmission } from './work-area-session-storage';

type Outcome = {kind:'pending'|'unknown'} | {kind:'success';workAreaId:string;name:string} | {kind:'failure';message:string};
interface Attempt { id:string; body:string; outcome:Outcome }
interface Episode { id:string; first:FirstSubmission; attempts:Attempt[]; sourceRaw?:string; sourceDraftRaw?:string }
interface Journal { version:1; siteId:string; identity:string; episodes:Episode[] }
type Port = Pick<Storage,'getItem'|'setItem'>;
type Result = {kind:'empty'|'invalid'|'unavailable'} | {kind:'found';journal:Journal};
const object=(v:unknown):v is Record<string,unknown>=>typeof v==='object' && v!==null && !Array.isArray(v);
const keys=(v:Record<string,unknown>,list:string[])=>Object.keys(v).length===list.length && list.every(k=>Object.hasOwn(v,k));
const validId=(id:unknown):id is string=>typeof id==='string' && /^[A-Za-z0-9_-]{16,128}$/.test(id);
const key=(site:string,identity:string)=>`ksi.work-area.episodes.v1:${encodeURIComponent(site)}:${identity}`;
function validOutcome(v:unknown):v is Outcome {
  if (!object(v)) return false;
  if (v.kind==='pending'||v.kind==='unknown') return keys(v,['kind']);
  if (v.kind==='success') return keys(v,['kind','workAreaId','name']) && typeof v.workAreaId==='string' && v.workAreaId!=='' && typeof v.name==='string';
  return v.kind==='failure' && keys(v,['kind','message']) && typeof v.message==='string';
}
export function readEpisodeJournal(storage:Port,siteId:string,identity:string):Result {
  if (!siteId || !/^v1-[a-f0-9]{64}$/.test(identity)) return {kind:'invalid'};
  try {
    const raw=storage.getItem(key(siteId,identity)); if(raw===null) return {kind:'empty'};
    const j:unknown=JSON.parse(raw);
    if(!object(j)||!keys(j,['version','siteId','identity','episodes'])||j.version!==1||j.siteId!==siteId||j.identity!==identity||!Array.isArray(j.episodes)) return {kind:'invalid'};
    const episodeIds=new Set<string>();
    const actionIds=new Set<string>();
    for(const e of j.episodes) {
      if(!object(e)||!(keys(e,['id','first','attempts']) || keys(e,['id','first','attempts','sourceRaw']) || keys(e,['id','first','attempts','sourceRaw','sourceDraftRaw']))||!validId(e.id)||episodeIds.has(e.id)||!validSubmission(e.first,siteId,identity)||!Array.isArray(e.attempts)) return {kind:'invalid'};
      if (Object.hasOwn(e,'sourceRaw')) {
        if (typeof e.sourceRaw !== 'string' || e.id !== firstMigrationId(e.sourceRaw)) return {kind:'invalid'};
        try { if (JSON.stringify(JSON.parse(e.sourceRaw)) !== JSON.stringify(e.first)) return {kind:'invalid'}; } catch { return {kind:'invalid'}; }
      }
      if (Object.hasOwn(e,'sourceDraftRaw')) {
        try {
          if(typeof e.sourceDraftRaw !== 'string') return {kind:'invalid'};
          const draft:unknown=JSON.parse(e.sourceDraftRaw);
          if(!object(draft)||!keys(draft,['version','siteId','identity','payload'])||draft.version!==1||draft.siteId!==siteId||draft.identity!==identity||!isEditDraft(draft.payload))return {kind:'invalid'};
        } catch {return {kind:'invalid'};}
      }
      if(e.first.version===2) { if(actionIds.has(e.first.requestId))return {kind:'invalid'}; actionIds.add(e.first.requestId); }
      episodeIds.add(e.id);
      const attemptIds=new Set<string>();
      for(const a of e.attempts) { if(!object(a)||!keys(a,['id','body','outcome'])||!validId(a.id)||attemptIds.has(a.id)||actionIds.has(a.id)||a.body!==e.first.body||!validOutcome(a.outcome)) return {kind:'invalid'}; attemptIds.add(a.id); actionIds.add(a.id); }
    }
    return {kind:'found',journal:j as unknown as Journal};
  } catch(e) {return e instanceof SyntaxError?{kind:'invalid'}:{kind:'unavailable'};}
}
function update(storage:Port,site:string,identity:string,mutate:(j:Journal)=>boolean):boolean {
  const current=readEpisodeJournal(storage,site,identity);
  if(current.kind!=='empty'&&current.kind!=='found') return false;
  const j:Journal=current.kind==='found'?current.journal:{version:1,siteId:site,identity,episodes:[]};
  if(!mutate(j)) return false;
  try { const raw=JSON.stringify(j);storage.setItem(key(site,identity),raw);return storage.getItem(key(site,identity))===raw; } catch{return false;}
}
export function appendEpisode(storage:Port,first:FirstSubmission,id:string,sourceRaw?:string,sourceDraftRaw?:string):boolean {
  if(!validId(id)||!validSubmission(first,first.siteId,first.identity)) return false;
  if(sourceRaw !== undefined) { try { if(JSON.stringify(JSON.parse(sourceRaw)) !== JSON.stringify(first)) return false; } catch { return false; } }
  if(sourceDraftRaw!==undefined) { try { const d:unknown=JSON.parse(sourceDraftRaw); if(!object(d)||!keys(d,['version','siteId','identity','payload'])||d.version!==1||d.siteId!==first.siteId||d.identity!==first.identity||!isEditDraft(d.payload)||sourceRaw===undefined)return false; } catch {return false;} }
  return update(storage,first.siteId,first.identity,j=>{if(j.episodes.some(e=>e.id===id || (first.version===2 && ((e.first.version===2 && e.first.requestId===first.requestId) || e.attempts.some(a=>a.id===first.requestId)))))return false;j.episodes.push({id,first,attempts:[],...(sourceRaw === undefined ? {} : {sourceRaw}),...(sourceDraftRaw === undefined ? {} : {sourceDraftRaw})});return true;});
}
export function appendAttempt(storage:Port,site:string,identity:string,episode:number,id:string):boolean {
  if(!validId(id))return false;
  return update(storage,site,identity,j=>{const e=j.episodes[episode];if(!e||j.episodes.some(item=>(item.first.version===2 && item.first.requestId===id)||item.attempts.some(a=>a.id===id)))return false;e.attempts.push({id,body:e.first.body,outcome:{kind:'pending'}});return true;});
}
export function settleAttempt(storage:Port,site:string,identity:string,episode:number,attempt:number,outcome:Outcome):boolean {
  if(!validOutcome(outcome)||outcome.kind==='pending')return false;
  return update(storage,site,identity,j=>{const a=j.episodes[episode]?.attempts[attempt];if(!a||a.outcome.kind!=='pending')return false;a.outcome=outcome;return true;});
}

/** Deterministic v1 migration key; the stored original is always compared as well. */
export function firstMigrationId(raw:string):string {
  return `first_${bytesToHex(sha256(utf8ToBytes(raw)))}`;
}
export function ensureFirstArchived(storage:Port, first:FirstSubmission, raw:string, draftRaw?:string):boolean {
  const id=firstMigrationId(raw);
  let result=readEpisodeJournal(storage,first.siteId,first.identity);
  if(result.kind==='invalid'||result.kind==='unavailable')return false;
  if(result.kind==='found') {
    const prior=result.journal.episodes.find(e=>e.id===id);
    if(prior) {
      if(first.version===1 || prior.sourceRaw!==raw || JSON.stringify(prior.first)!==JSON.stringify(first))return false;
      if(draftRaw === undefined || prior.sourceDraftRaw===draftRaw)return true;
      if(prior.sourceDraftRaw!==undefined)return false;
      try {
        const draft:unknown=JSON.parse(draftRaw);
        if(!object(draft)||!keys(draft,['version','siteId','identity','payload'])||draft.version!==1||draft.siteId!==first.siteId||draft.identity!==first.identity||!isEditDraft(draft.payload))return false;
      } catch {return false;}
      // Upgrade a partially migrated legacy v1 record without replacing its
      // original or attempts. A failed readback is resolved by re-reading.
      update(storage,first.siteId,first.identity,j=>{
        const entry=j.episodes.find(e=>e.id===id);
        if(!entry || entry.sourceRaw!==raw || entry.sourceDraftRaw!==undefined || JSON.stringify(entry.first)!==JSON.stringify(first))return false;
        entry.sourceDraftRaw=draftRaw;return true;
      });
      const checked=readEpisodeJournal(storage,first.siteId,first.identity);
      if(checked.kind!=='found')return false;
      const upgraded=checked.journal.episodes.find(e=>e.id===id);
      return !!upgraded && upgraded.sourceRaw===raw && upgraded.sourceDraftRaw===draftRaw && JSON.stringify(upgraded.first)===JSON.stringify(first);
    }
  }
  if(!appendEpisode(storage,first,id,raw,draftRaw)) {
    // A successful set followed by failed readback is ambiguous; only a fresh
    // validated read can prove that this exact source was preserved.
    result=readEpisodeJournal(storage,first.siteId,first.identity);
    if(result.kind!=='found') return false;
    const prior=result.journal.episodes.find(e=>e.id===id);
    return !!prior && (draftRaw === undefined || prior.sourceDraftRaw===draftRaw) && prior.sourceRaw===raw && JSON.stringify(prior.first)===JSON.stringify(first);
  }
  result=readEpisodeJournal(storage,first.siteId,first.identity);
  if(result.kind!=='found')return false;
  const prior=result.journal.episodes.find(e=>e.id===id);
  return !!prior && (draftRaw === undefined || prior.sourceDraftRaw===draftRaw) && prior.sourceRaw===raw && JSON.stringify(prior.first)===JSON.stringify(first);
}
