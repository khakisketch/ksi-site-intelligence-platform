/** @vitest-environment jsdom */
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
vi.mock('next/navigation', () => ({usePathname:()=>'/sites/created',useSearchParams:()=>new URLSearchParams()}));
import {AccountDisplayBoundary} from '@/components/nav/AccountDisplayBoundary';
import {SiteListProvider,useSidebarSites,useSiteListRefresh} from '@/components/nav/SiteListContext';
const a='v1-'+'a'.repeat(64),b='v1-'+'b'.repeat(64);
const json=(x:unknown)=>new Response(JSON.stringify(x));
function Body(){ const sites=useSidebarSites(),refresh=useSiteListRefresh(); return <><button onClick={()=>void refresh("created")}>refresh</button><input aria-label="raw" defaultValue="raw"/><div>{sites.map(s=>s.name)}</div></>; }
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();vi.restoreAllMocks();});
it('holds pending subtree and rejects old A response over A→B→A',async()=>{
 vi.spyOn(document,'hasFocus').mockReturnValue(true); let account=a; let resolve!:(value:Response)=>void;
 vi.stubGlobal('fetch',vi.fn((url:string)=>url==='/api/shell-sites'?new Promise<Response>(r=>{resolve=r;}):Promise.resolve(json({fingerprint:account}))));
 render(<AccountDisplayBoundary fingerprint={a}><SiteListProvider fingerprint={a} sites={[]}><Body/></SiteListProvider></AccountDisplayBoundary>);
 await waitFor(()=>expect(screen.queryByText('계정 다시 확인')).toBeNull());
 const input=screen.getByLabelText('raw') as HTMLInputElement; fireEvent.change(input,{target:{value:'pending'}}); fireEvent.click(screen.getByText('refresh'));
 await waitFor(() => expect(resolve).toBeDefined());
 account=b; fireEvent.blur(window); fireEvent.focus(window); await waitFor(()=>expect(screen.getByRole('status').getAttribute('data-account-display-state')).toBe('locked'));
 expect(input.isConnected).toBe(true); expect(input.value).toBe('pending');
 account=a; fireEvent.click(screen.getByText('계정 다시 확인')); await waitFor(()=>expect(screen.queryByText('계정 다시 확인')).toBeNull());
 await act(async()=>{resolve(json({fingerprint:a,sites:[{siteId:'created',name:'stale',status:'UNMAPPED'}]}));});
 expect(screen.queryByText('stale')).toBeNull(); expect(screen.getByLabelText('raw')).toBe(input); expect(input.value).toBe('pending');
});
it('identity deadline locks the original subtree, then permits account recovery and retry',async()=>{
 vi.spyOn(document,'hasFocus').mockReturnValue(true);
 let hang=false; let resolve!:(value:Response)=>void;
 vi.stubGlobal('fetch',vi.fn(()=>hang ? new Promise<Response>(r=>{resolve=r;}) : Promise.resolve(json({fingerprint:a}))));
 const {SiteListRefreshNotice}=await import('@/components/nav/SiteListRefreshNotice');
 render(<AccountDisplayBoundary fingerprint={a}><SiteListProvider fingerprint={a} sites={[]}><SiteListRefreshNotice/><Body/></SiteListProvider></AccountDisplayBoundary>);
 await waitFor(()=>expect(screen.queryByText('계정 다시 확인')).toBeNull());
 const input=screen.getByLabelText('raw') as HTMLInputElement; fireEvent.change(input,{target:{value:'unsaved'}});
 vi.useFakeTimers(); hang=true; fireEvent.click(screen.getByText('refresh'));
 await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});
 const root=document.querySelector<HTMLElement>('[data-account-display-root]')!;
 expect(root.hidden).toBe(true); expect(input.isConnected).toBe(true); expect(input.value).toBe('unsaved');
 hang=false; fireEvent.click(screen.getByText('계정 다시 확인')); await act(async()=>{for(let i=0;i<15;i++) await Promise.resolve();});
 expect(root.hidden).toBe(false); expect(screen.getByText('현장 메뉴 다시 확인')).toBeTruthy();
 await act(async()=>{resolve(json({fingerprint:a})); await Promise.resolve();});
 expect(screen.getByText('현장 메뉴 다시 확인')).toBeTruthy(); expect(screen.getByLabelText('raw')).toBe(input); expect(input.value).toBe('unsaved');
 vi.useRealTimers();
});
