/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const env = vi.hoisted(() => ({ generation: 0, locked: false, invalidate: vi.fn() }));
vi.mock('@/components/nav/AccountDisplayBoundary', () => ({ useAccountDisplayLock: () => ({locked: () => env.locked, generation: () => env.generation, invalidate: env.invalidate}) }));
import { SiteListProvider, useSidebarSites, useSiteListRefresh } from '@/components/nav/SiteListContext';
import { SiteListRefreshNotice } from '@/components/nav/SiteListRefreshNotice';
const fingerprint = 'v1-' + 'a'.repeat(64);
const old = [{siteId:'old', name:'기존 현장', status:'UNMAPPED' as const}];
const ok = (body:unknown) => new Response(JSON.stringify(body));
function App() { const refresh=useSiteListRefresh(), sites=useSidebarSites(); return <><SiteListRefreshNotice/><button onClick={()=>void refresh('new')}>브리핑 이동</button><input aria-label="입력" defaultValue="보존"/><div>{sites.map(s=>s.name).join(',')}</div></>; }
beforeEach(()=>{vi.useFakeTimers(); env.generation=0; env.locked=false; env.invalidate.mockReset();});
afterEach(()=>{cleanup(); vi.useRealTimers(); vi.unstubAllGlobals();});
it('recovers from a site list fetch that never settles without losing existing data', async()=>{
 vi.stubGlobal('fetch',vi.fn((url:string)=>url==='/api/account-identity' ? Promise.resolve(ok({fingerprint})) : new Promise<Response>(()=>{})));
 render(<SiteListProvider sites={old} fingerprint={fingerprint}><App/></SiteListProvider>);
 const input=screen.getByLabelText('입력') as HTMLInputElement; fireEvent.change(input,{target:{value:'미저장'}}); fireEvent.click(screen.getByText('브리핑 이동'));
 await act(async()=>{await Promise.resolve(); await Promise.resolve();});
 expect(screen.getByText('현장 메뉴를 확인하고 있습니다.')).toBeTruthy();
 await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});
 expect(screen.getByText(/현장 메뉴를 확인하지 못했습니다/)).toBeTruthy(); expect(screen.getByText('현장 메뉴 다시 확인')).toBeTruthy();
 expect(screen.getByText('기존 현장')).toBeTruthy(); expect(screen.getByLabelText('입력')).toBe(input); expect(input.value).toBe('미저장');
});
it.each(['identity fetch','identity body','sites fetch','sites body','post identity body'] as const)('bounds %s even when the dummy ignores abort', async phase => {
 let identityCalls=0; let signal: AbortSignal | undefined;
 const never = new Promise<never>(()=>{});
 const fetcher=vi.fn((url:string, init?:RequestInit) => {
   const identity=url==='/api/account-identity'; if(identity) identityCalls++;
   const delayed = (phase==='identity fetch' && identity && identityCalls===1) || (phase==='sites fetch' && !identity);
   const slowBody = (phase==='identity body' && identity && identityCalls===1) || (phase==='sites body' && !identity) || (phase==='post identity body' && identity && identityCalls===2);
   if(delayed || slowBody) signal=init?.signal ?? undefined;
   if(delayed) return never;
   if(slowBody) return Promise.resolve({ok:true, json:()=>never} as unknown as Response);
   return Promise.resolve(ok(identity ? {fingerprint} : {fingerprint,sites:[{siteId:'new',name:'신규 현장',status:'UNMAPPED'}]}));
 });
 vi.stubGlobal('fetch',fetcher);
 render(<SiteListProvider sites={old} fingerprint={fingerprint}><App/></SiteListProvider>);
 fireEvent.click(screen.getByText('브리핑 이동'));
 await act(async()=>{for(let i=0;i<20;i++) await Promise.resolve();});
 expect(signal).toBeDefined();
 await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});
 expect(signal?.aborted).toBe(true);
 expect(screen.getByText(/현장 메뉴를 확인하지 못했습니다/)).toBeTruthy(); expect(screen.getByText('기존 현장')).toBeTruthy();
 expect(env.invalidate).toHaveBeenCalledTimes(phase.includes('identity') ? 1 : 0);
 expect(vi.getTimerCount()).toBe(0);
});
it('a late abort-ignoring body cannot replace a successful retry', async()=>{
 let resolve!: (body:unknown)=>void; let reads=0; let oldSignal:AbortSignal|undefined;
 const delayed=new Promise<unknown>(r=>{resolve=r;});
 vi.stubGlobal('fetch',vi.fn((url:string,init?:RequestInit)=>{
   if(url==='/api/account-identity') return Promise.resolve(ok({fingerprint}));
   if(++reads===1) {oldSignal=init?.signal ?? undefined; return Promise.resolve({ok:true,json:()=>delayed} as unknown as Response);}
   return Promise.resolve(ok({fingerprint,sites:[{siteId:'new',name:'확인된 최신 현장',status:'UNMAPPED'}]}));
 }));
 render(<SiteListProvider sites={old} fingerprint={fingerprint}><App/></SiteListProvider>);
 fireEvent.click(screen.getByText('브리핑 이동')); await act(async()=>{for(let i=0;i<20;i++) await Promise.resolve();});
 await act(async()=>{await vi.advanceTimersByTimeAsync(10000);}); expect(oldSignal?.aborted).toBe(true);
 fireEvent.click(screen.getByText('현장 메뉴 다시 확인')); await act(async()=>{for(let i=0;i<30;i++) await Promise.resolve();});
 expect(screen.getByText('확인된 최신 현장')).toBeTruthy();
 await act(async()=>{resolve({fingerprint,sites:[{siteId:'new',name:'오래된 현장',status:'UNMAPPED'}]}); await Promise.resolve();});
 expect(screen.queryByText('오래된 현장')).toBeNull(); expect(screen.getByText('확인된 최신 현장')).toBeTruthy(); expect(vi.getTimerCount()).toBe(0);
});
it('a new attempt cancels the first deadline and only the latest may finish', async()=>{
 let firstSignal:AbortSignal|undefined; let calls=0;
 vi.stubGlobal('fetch',vi.fn((url:string,init?:RequestInit)=>{
   if(url==='/api/account-identity') return Promise.resolve(ok({fingerprint}));
   if(++calls===1){firstSignal=init?.signal ?? undefined; return new Promise<Response>(()=>{});}
   return Promise.resolve(ok({fingerprint,sites:[{siteId:'new',name:'최신 현장',status:'UNMAPPED'}]}));
 }));
 render(<SiteListProvider sites={old} fingerprint={fingerprint}><App/></SiteListProvider>);
 fireEvent.click(screen.getByText('브리핑 이동')); await act(async()=>{for(let i=0;i<20;i++) await Promise.resolve();});
 fireEvent.click(screen.getByText('브리핑 이동')); await act(async()=>{for(let i=0;i<30;i++) await Promise.resolve();});
 expect(firstSignal?.aborted).toBe(true); expect(screen.getByText('최신 현장')).toBeTruthy();
 await act(async()=>{await vi.advanceTimersByTimeAsync(20000);}); expect(screen.queryByText(/현장 메뉴를 확인하지 못했습니다/)).toBeNull(); expect(vi.getTimerCount()).toBe(0);
});
it('unmount cancels the active request and timer', async()=>{
 let signal:AbortSignal|undefined;
 vi.stubGlobal('fetch',vi.fn((_url:string,init?:RequestInit)=>{signal=init?.signal ?? undefined; return new Promise<Response>(()=>{});}));
 const view=render(<SiteListProvider sites={old} fingerprint={fingerprint}><App/></SiteListProvider>);
 fireEvent.click(screen.getByText('브리핑 이동')); expect(signal).toBeDefined(); view.unmount();
 await act(async()=>{await Promise.resolve();}); expect(signal?.aborted).toBe(true); expect(vi.getTimerCount()).toBe(0);
});
