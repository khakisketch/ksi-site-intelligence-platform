// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";
import { completeFreshLoginDestination, loadFreshLoginDestination } from "@/components/nav/fresh-login-navigation";
const marker = "ksi.login-fresh-document.v1";
beforeEach(() => { sessionStorage.clear(); window.history.replaceState(null, "", "/sites/test?workAreaId=one#map"); });
it("does not reload a different or stale router location", () => {
  expect(loadFreshLoginDestination("/sites/other")).toBe(false);
  expect(sessionStorage.getItem(marker)).toBeNull();
});
it("refuses a second automatic transition and leaves draft data alone", () => {
  sessionStorage.setItem(marker,"pending");
  sessionStorage.setItem("draft-example","untouched");
  expect(loadFreshLoginDestination("/sites/test")).toBe(false);
  completeFreshLoginDestination();
  expect(sessionStorage.getItem(marker)).toBeNull();
  expect(sessionStorage.getItem("draft-example")).toBe("untouched");
});
it("fails closed when session storage cannot enforce the loop guard", () => {
  vi.spyOn(Storage.prototype,"getItem").mockImplementation(() => {throw new Error("blocked");});
  expect(loadFreshLoginDestination("/sites/test")).toBe(false);
  vi.restoreAllMocks();
});

it("reloads the current document once without changing query or fragment", () => {
  const reload = vi.fn();
  const storage = new Map<string, string>();
  const browser = {
    location: { pathname: "/sites/test", href: "http://localhost/sites/test?workAreaId=one#map", reload },
    sessionStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => { storage.set(key, value); } },
  };
  expect(loadFreshLoginDestination("/sites/test", browser)).toBe(true);
  expect(reload).toHaveBeenCalledTimes(1);
  expect(browser.location.href).toBe("http://localhost/sites/test?workAreaId=one#map");
  expect(loadFreshLoginDestination("/sites/test", browser)).toBe(false);
  expect(reload).toHaveBeenCalledTimes(1);
});

it("does not navigate if storage is denied and handles a reload exception", () => {
  const reload = vi.fn();
  const denied = { location: { pathname: "/sites/test", reload }, sessionStorage: { getItem: () => { throw new Error("denied"); }, setItem: () => {} } };
  expect(loadFreshLoginDestination("/sites/test", denied)).toBe(false);
  expect(reload).not.toHaveBeenCalled();
  const throws = { location: { pathname: "/sites/test", reload: () => { throw new Error("denied"); } }, sessionStorage: { getItem: () => null, setItem: () => {} } };
  expect(loadFreshLoginDestination("/sites/test", throws)).toBe(false);
});
