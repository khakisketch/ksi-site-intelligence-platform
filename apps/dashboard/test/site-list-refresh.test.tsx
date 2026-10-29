/** @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const env = vi.hoisted(() => ({ path: '/sites/new', generation: 0, locked: false, push: vi.fn() }));
vi.mock('next/navigation', () => ({usePathname: () => env.path, useSearchParams: () => new URLSearchParams(), useRouter: () => ({push: env.push})}));
vi.mock('next/link', () => ({default: ({href, children, ...props}: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a>}));
vi.mock('@/components/nav/AccountDisplayBoundary', () => ({useAccountDisplayLock: () => ({ locked: () => env.locked, generation: () => env.generation })}));
import { SiteListProvider, useSidebarSites, useSiteListRefresh } from '@/components/nav/SiteListContext';
import { DesktopSidebar } from '@/components/nav/DesktopSidebar';
import { CommandPalette } from '@/components/console/CommandPalette';
import { SiteContextNav } from '@/components/nav/SiteContextNav';
const fingerprint = 'v1-' + 'a'.repeat(64);
function Shell() {
 const sites = useSidebarSites(); const refresh = useSiteListRefresh?.() ?? (() => Promise.resolve());
 return <><button onClick={() => {void refresh("new-id"); env.path = '/sites/new-id';}}>현장 브리핑으로 이동</button><input aria-label="원문" defaultValue="보존"/><SiteContextNav sites={sites}/><span data-testid="count">{sites.length}</span></>;
}
afterEach(() => {cleanup(); vi.restoreAllMocks(); env.path='/sites/new'; env.locked=false; env.generation=0; env.push.mockClear(); window.history.replaceState({}, '', '/');});
it('explicit briefing entry refreshes the server-confirmed site without remounting input', async () => {
 vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({fingerprint, sites:[{siteId:'new-id', name:'신규 현장', status:'UNMAPPED'}]}), {status:200})));
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><Shell/></SiteListProvider>);
 const input = screen.getByLabelText('원문') as HTMLInputElement; fireEvent.change(input,{target:{value:'미저장'}});
 fireEvent.click(screen.getByRole('button',{name:'현장 브리핑으로 이동'}));
 await waitFor(() => expect(screen.getByText('신규 현장')).toBeTruthy());
 expect(screen.getByRole('navigation',{name:'현재 현장 메뉴'})).toBeTruthy();
 expect(screen.getByTestId('count').textContent).toBe('1'); expect(input.value).toBe('미저장');
});
it('discards a response across lock and return to the same account', async () => {
 let resolve!: (r: Response) => void;
 vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { resolve = r; })));
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><Shell/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'현장 브리핑으로 이동'}));
 env.locked = true; env.generation++; env.locked = false; env.generation++;
 resolve(new Response(JSON.stringify({fingerprint,sites:[{siteId:'new-id',name:'stale A',status:'UNMAPPED'}]})));
 await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('0'));
 await new Promise(r => setTimeout(r,0));
 expect(screen.queryByText('stale A')).toBeNull(); expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
});
it('failed list or mismatched post-read identity does not publish sites', async () => {
 const fetcher = vi.fn().mockResolvedValueOnce(new Response('{}',{status:403})); vi.stubGlobal('fetch', fetcher);
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><Shell/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'현장 브리핑으로 이동'}));
 await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
 expect(screen.getByTestId('count').textContent).toBe('0');
 fetcher.mockResolvedValueOnce(new Response(JSON.stringify({fingerprint,sites:[{siteId:'new-id',name:'private',status:'UNMAPPED'}]}))).mockResolvedValueOnce(new Response(JSON.stringify({fingerprint:'v1-'+'b'.repeat(64)})));
 fireEvent.click(screen.getByRole('button',{name:'현장 브리핑으로 이동'}));
 await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
 expect(screen.queryByText('private')).toBeNull();
});
it('latest refresh wins even if previous request returns last', async () => {
 let first!: (r: Response) => void; let calls=0;
 const fetcher=vi.fn((url:string) => {
   if(url === '/api/account-identity') return Promise.resolve(new Response(JSON.stringify({fingerprint})));
   if(++calls === 1) return new Promise<Response>(r=>{first=r;});
   return Promise.resolve(new Response(JSON.stringify({fingerprint,sites:[{siteId:'new-id',name:'latest',status:'UNMAPPED'}]})));
 });
 vi.stubGlobal('fetch',fetcher); render(<SiteListProvider sites={[]} fingerprint={fingerprint}><Shell/></SiteListProvider>);
 const button=screen.getByRole('button',{name:'현장 브리핑으로 이동'}); fireEvent.click(button);
 await waitFor(()=>expect(first).toBeDefined()); fireEvent.click(button); await screen.findByText('latest');
 first(new Response(JSON.stringify({fingerprint,sites:[{siteId:'new-id',name:'older',status:'UNMAPPED'}]})));
 await new Promise(r=>setTimeout(r,0)); expect(screen.queryByText('older')).toBeNull();
});
it('rail count, current site, switcher and palette share refreshed list', async () => {
 HTMLElement.prototype.scrollIntoView = vi.fn();
 const all = [{siteId:'new-id',name:'신규 현장',status:'UNMAPPED'},{siteId:'old-id',name:'기존 현장',status:'UNMAPPED'}];
 vi.stubGlobal('fetch',vi.fn(async (url:string) => new Response(JSON.stringify(url === '/api/shell-sites' ? {fingerprint,sites:all} : {fingerprint}))));
 function Parts() { const refresh = useSiteListRefresh(); return <><button onClick={() => { env.path='/sites/new-id'; void refresh('new-id'); }}>들어가기</button><DesktopSidebar sites={[]} counts={{}}/><CommandPalette items={[]}/></>; }
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><Parts/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'들어가기'}));
 await screen.findByRole('button',{name:'현장 변경: 신규 현장'});
 expect(screen.getByRole('link',{name:/현장.*2/})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'현장 변경: 신규 현장'}));
 expect(screen.getByRole('link',{name:/기존 현장/}).getAttribute('href')).toBe('/sites/old-id');
 fireEvent.keyDown(document,{key:'Escape'});
 fireEvent.keyDown(window,{key:'k',ctrlKey:true});
 const dialog = screen.getByRole('dialog',{name:'검색 및 이동'});
 expect(dialog.textContent).toContain('신규 현장'); expect(dialog.textContent).toContain('기존 현장');
 fireEvent.keyDown(window,{key:'Escape'}); fireEvent.click(screen.getByRole('button',{name:'주 메뉴 접기'}));
 expect(screen.getByRole('link',{name:'현재 현장: 신규 현장'})).toBeTruthy();
});
it('failed list announces recovery and explicit retry checks account before showing the site', async () => {
 const {SiteListRefreshNotice}=await import('@/components/nav/SiteListRefreshNotice');
 let fail=true; const fetcher=vi.fn(async (url:string) => {
   if(url === '/api/account-identity') return new Response(JSON.stringify({fingerprint}));
   return fail ? new Response('{}',{status:403}) : new Response(JSON.stringify({fingerprint,sites:[{siteId:'new-id',name:'복구 현장',status:'UNMAPPED'}]}));
 });
 vi.stubGlobal('fetch',fetcher);
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><SiteListRefreshNotice/><Shell/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'현장 브리핑으로 이동'}));
 expect(await screen.findByText(/현장 메뉴를 확인하지 못했습니다/)).toBeTruthy();
 expect(screen.getByTestId('count').textContent).toBe('0');
 fail=false; fireEvent.click(screen.getByRole('button',{name:'현장 메뉴 다시 확인'}));
 await screen.findByText('복구 현장');
 expect(screen.queryByText(/현장 메뉴를 확인하지 못했습니다/)).toBeNull();
 expect(fetcher.mock.calls.filter(([url]) => url === '/api/account-identity')).toHaveLength(3);
});
it.each([401,403,500])('withholds new data on list status %s', async status => {
 const {SiteListRefreshNotice}=await import('@/components/nav/SiteListRefreshNotice');
 vi.stubGlobal('fetch',vi.fn(async (url:string)=>url==='/api/account-identity' ? new Response(JSON.stringify({fingerprint})) : new Response('{}',{status})));
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><SiteListRefreshNotice/><Shell/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'현장 브리핑으로 이동'}));
 await screen.findByText(/현장 메뉴를 확인하지 못했습니다/); expect(screen.getByTestId('count').textContent).toBe('0');
});

it('uses the refreshed site for header scope when opening the palette after first registration', async () => {
 HTMLElement.prototype.scrollIntoView = vi.fn();
 const ref = `ksa-v1-${'c'.repeat(64)}`;
 vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url === '/api/shell-sites' ? {fingerprint, sites:[{siteId:'new-id', name:'신규 현장', status:'UNMAPPED'}]} : {fingerprint}))));
 function Parts() {
   const refresh = useSiteListRefresh(); const sites = useSidebarSites();
   return <><span data-testid="refreshed-sites">{sites.map(site => site.name).join(',')}</span><button onClick={() => void refresh('new-id')}>현장 목록 확인</button>
     <header data-site-nav="true" data-site-id="new-id" data-work-area-id="wa-a" data-asset-ref={ref}/>
     <CommandPalette items={[]} /></>;
 }
 env.path='/sites/new-id/analysis'; window.history.replaceState({}, '', '/sites/new-id/analysis');
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><Parts/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'현장 목록 확인'}));
 await waitFor(() => expect(screen.getByTestId('refreshed-sites').textContent).toBe('신규 현장'));
 fireEvent.keyDown(window,{key:'k',ctrlKey:true});
 expect(screen.getByRole('dialog',{name:'검색 및 이동'}).textContent).toContain('신규 현장');
 const option = screen.getAllByRole('option').find(item => item.textContent?.startsWith('자료'));
 expect(option).toBeTruthy(); fireEvent.click(option!);
 expect(env.push).toHaveBeenCalledWith(`/sites/new-id/spatial-assets?workAreaId=wa-a&assetRef=${ref}`);
});

it('refreshed list does not authorize an old site or import a cross-site bridge', async () => {
 HTMLElement.prototype.scrollIntoView = vi.fn();
 const ref = `ksa-v1-${'d'.repeat(64)}`;
 vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url === '/api/shell-sites' ? {fingerprint, sites:[{siteId:'new-id',name:'신규 현장',status:'UNMAPPED'}]} : {fingerprint}))));
 function Parts() {
   const refresh=useSiteListRefresh(), sites=useSidebarSites();
   return <><button onClick={() => void refresh('new-id')}>목록 확인</button><span data-testid="confirmed">{sites.map(site=>site.name).join(',')}</span>
     <header data-site-nav="true" data-site-id="old-id" data-work-area-id="wa-old" data-asset-ref={ref}/>
     <CommandPalette items={[{key:'site:old-id',label:'이전 현장',group:'현장',href:'/sites/old-id'}]}/></>;
 }
 env.path='/sites/new-id/analysis'; window.history.replaceState({}, '', env.path);
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><Parts/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'목록 확인'})); await waitFor(()=>expect(screen.getByTestId('confirmed').textContent).toBe('신규 현장'));
 fireEvent.keyDown(window,{key:'k',ctrlKey:true});
 expect(screen.queryByText('이전 현장')).toBeNull();
 fireEvent.click(screen.getAllByRole('option').find(item=>item.textContent?.startsWith('자료'))!);
 expect(env.push).toHaveBeenCalledWith('/sites/new-id/spatial-assets');
});
it('refreshed site preserves an explicit URL scope rather than replacing it with the header', async () => {
 HTMLElement.prototype.scrollIntoView = vi.fn(); const ref = `ksa-v1-${'e'.repeat(64)}`;
 vi.stubGlobal('fetch',vi.fn(async (url:string)=>new Response(JSON.stringify(url==='/api/shell-sites' ? {fingerprint,sites:[{siteId:'new-id',name:'신규 현장',status:'UNMAPPED'}]} : {fingerprint}))));
 function Parts() { const refresh=useSiteListRefresh(), sites=useSidebarSites(); return <><button onClick={()=>void refresh('new-id')}>목록 확인</button><span data-testid="confirmed">{sites.length}</span>
   <header data-site-nav="true" data-site-id="new-id" data-work-area-id="wa-header" data-asset-ref={ref}/><CommandPalette items={[]}/></>; }
 env.path='/sites/new-id/analysis'; window.history.replaceState({}, '', `${env.path}?workAreaId=wa-explicit`);
 render(<SiteListProvider sites={[]} fingerprint={fingerprint}><Parts/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'목록 확인'})); await waitFor(()=>expect(screen.getByTestId('confirmed').textContent).toBe('1'));
 fireEvent.keyDown(window,{key:'k',ctrlKey:true}); fireEvent.click(screen.getAllByRole('option').find(item=>item.textContent?.startsWith('자료'))!);
 expect(env.push).toHaveBeenCalledWith('/sites/new-id/spatial-assets?workAreaId=wa-explicit');
});
it('failed refresh retains the original confirmed site bridge without authorizing the new site', async () => {
 HTMLElement.prototype.scrollIntoView = vi.fn(); const ref = `ksa-v1-${'f'.repeat(64)}`;
 vi.stubGlobal('fetch', vi.fn(async (url:string) => url === '/api/shell-sites' ? new Response('{}',{status:403}) : new Response(JSON.stringify({fingerprint}))));
 const {SiteListRefreshNotice}=await import('@/components/nav/SiteListRefreshNotice');
 function Parts() { const refresh=useSiteListRefresh(); return <><button onClick={()=>void refresh('new-id')}>목록 확인</button><SiteListRefreshNotice/>
   <header data-site-nav="true" data-site-id="old-id" data-work-area-id="wa-old" data-asset-ref={ref}/>
   <CommandPalette items={[{key:'site:old-id',label:'기존 현장',group:'현장',href:'/sites/old-id'}]}/></>; }
 env.path='/sites/old-id/analysis'; window.history.replaceState({}, '', env.path);
 render(<SiteListProvider sites={[{siteId:'old-id',name:'기존 현장',status:'UNMAPPED'}]} fingerprint={fingerprint}><Parts/></SiteListProvider>);
 fireEvent.click(screen.getByRole('button',{name:'목록 확인'})); await screen.findByText(/현장 메뉴를 확인하지 못했습니다/);
 fireEvent.keyDown(window,{key:'k',ctrlKey:true});
 fireEvent.click(screen.getAllByRole('option').find(item=>item.textContent?.startsWith('자료'))!);
 expect(env.push).toHaveBeenCalledWith(`/sites/old-id/spatial-assets?workAreaId=wa-old&assetRef=${ref}`);
});
