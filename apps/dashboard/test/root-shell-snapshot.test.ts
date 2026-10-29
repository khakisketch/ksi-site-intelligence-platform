import { beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({token: vi.fn(), core: vi.fn()}));
vi.mock("@/lib/core-api/session", () => ({getSessionToken: mocks.token}));
vi.mock("@/lib/core-api/client", () => ({coreFetchWithToken: mocks.core}));
import { readRootShellSnapshot } from "@/components/nav/root-shell-snapshot";
beforeEach(() => { vi.resetAllMocks(); mocks.token.mockResolvedValue("token-a"); });
it("derives identity and site list with the very same resolved token", async () => {
  mocks.core.mockImplementation(async (path: string) => path === "/v1/auth/whoami" ? {organizationId:"org-a",principalId:"alice"} : {sites:[{siteId:"a",name:"A"}]});
  const snapshot = await readRootShellSnapshot();
  expect(snapshot?.sites?.[0].name).toBe("A");
  expect(snapshot?.fingerprint).toMatch(/^v1-[0-9a-f]{64}$/);
  expect(mocks.token).toHaveBeenCalledTimes(1);
  expect(mocks.core.mock.calls.map(([path, token]) => [path, token])).toEqual([["/v1/auth/whoami", "token-a"], ["/v1/sites", "token-a"]]);
});
it("fails closed without a verified identity and never fetches sites", async () => {
  mocks.core.mockResolvedValueOnce({organizationId:"bad/org",principalId:"alice"});
  expect(await readRootShellSnapshot()).toBeNull();
  expect(mocks.core).toHaveBeenCalledTimes(1);
});
it("keeps identity while list failure remains unknown", async () => {
  mocks.core.mockResolvedValueOnce({organizationId:"org-a",principalId:"alice"}).mockRejectedValueOnce(new Error("offline"));
  expect((await readRootShellSnapshot())?.sites).toBeNull();
});
