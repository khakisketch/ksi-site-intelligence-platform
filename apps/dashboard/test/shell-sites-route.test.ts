import { beforeEach, expect, it, vi } from 'vitest';
const mock = vi.hoisted(() => ({token:vi.fn(), core:vi.fn(), fp:vi.fn()}));
vi.mock('server-only', () => ({}));
vi.mock('@/lib/core-api/session', () => ({getSessionToken: mock.token}));
vi.mock('@/lib/core-api/client', () => ({coreFetchWithToken: mock.core}));
vi.mock('@/lib/core-api/work-order-continuity', () => ({continuityFingerprint: mock.fp}));
import { GET } from '@/app/api/shell-sites/route';
import { NextRequest } from 'next/server';
const a = 'v1-'+ 'a'.repeat(64), b = 'v1-'+ 'b'.repeat(64);
const req = () => new NextRequest('http://localhost/api/shell-sites',{headers:{'x-ksi-continuity-fingerprint':a}});
beforeEach(() => {vi.resetAllMocks(); mock.token.mockResolvedValue('one-token'); mock.fp.mockReturnValue(a);});
it('reads only minimal sites with same authorized token, no-store', async () => {
 mock.core.mockResolvedValueOnce({principalId:'a'}).mockResolvedValueOnce({sites:[{siteId:'s',name:'name',status:'UNMAPPED',aoi:'secret'}]});
 const res = await GET(req()); expect(res.status).toBe(200); expect(res.headers.get('cache-control')).toBe('private, no-store');
 expect(await res.json()).toEqual({fingerprint:a,sites:[{siteId:'s',name:'name',status:'UNMAPPED'}]});
 expect(mock.core.mock.calls).toEqual([['/v1/auth/whoami','one-token'],['/v1/sites','one-token']]);
});
it('changed identity stops before site query', async () => {
 mock.core.mockResolvedValueOnce({principalId:'b'}); mock.fp.mockReturnValue(b);
 expect((await GET(req())).status).toBe(409); expect(mock.core).toHaveBeenCalledTimes(1);
});
it('read failures do not manufacture empty list', async () => {
 mock.core.mockResolvedValueOnce({principalId:'a'}).mockRejectedValueOnce(new Error('denied'));
 const res = await GET(req()); expect(res.status).toBe(503); expect(await res.json()).toEqual({});
});
it('invalid claims and malformed or partial Core lists fail closed', async () => {
 const invalid = new NextRequest('http://localhost/api/shell-sites',{headers:{'x-ksi-continuity-fingerprint':'bad'}});
 expect((await GET(invalid)).status).toBe(400); expect(mock.token).not.toHaveBeenCalled();
 for (const sites of [null, {}, [{siteId:'one',name:'ok',status:'UNMAPPED'},{siteId:'two',name:'bad'}], [{siteId:'one',name:'ok',status:'INVALID'}]]) {
   mock.core.mockReset().mockResolvedValueOnce({principalId:'a'}).mockResolvedValueOnce({sites});
   const res=await GET(req()); expect(res.status).toBe(502); expect(await res.json()).toEqual({});
 }
});
