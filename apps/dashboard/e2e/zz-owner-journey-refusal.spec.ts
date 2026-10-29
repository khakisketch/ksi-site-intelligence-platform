import { expect, test } from "@playwright/test";

import {
  hasOnlyLoopbackAddresses,
  isLoopbackHostname,
  loopbackInterfacesVerdict,
  requireLoopbackOnlyInterfaces,
  type InterfaceAddress,
} from "./fixtures/owner-journey-network-guard";

// Negative tests for the owner-journey network boundary. These run WITHOUT
// any opt-in, WITHOUT a browser, and WITHOUT network access: they assert the
// refusal predicates themselves, so a normal-network host is covered by
// passing tests here while the mutating probe (zz-owner-journey-probe) is
// refused there by the `requireLoopbackOnlyInterfaces` tripwire before any
// navigation/mutation.
// This file must never acquire page/context fixtures, navigation, or I/O.

function iface(
  address: string | null,
  internal: boolean | null,
): InterfaceAddress {
  return { address, internal };
}

test("loopback hostnames include the bracketed IPv6 form Node reports", () => {
  expect(isLoopbackHostname("127.0.0.1")).toBe(true);
  expect(isLoopbackHostname("localhost")).toBe(true);
  expect(isLoopbackHostname("::1")).toBe(true);
  // Node's URL parser keeps the brackets: new URL("http://[::1]").hostname.
  expect(isLoopbackHostname("[::1]")).toBe(true);
  expect(isLoopbackHostname("example.invalid")).toBe(false);
  expect(isLoopbackHostname("100.116.163.1")).toBe(false);
  expect(isLoopbackHostname("10.255.255.1")).toBe(false);
  expect(isLoopbackHostname("")).toBe(false);
});

test("a normal multi-interface host is refused", () => {
  const normalHost: NodeJS.Dict<InterfaceAddress[]> = {
    lo: [iface("127.0.0.1", true), iface("::1", true)],
    eth0: [iface("172.17.0.2", false)],
    tailscale0: [iface("100.116.163.1", false)],
  };
  expect(hasOnlyLoopbackAddresses(normalHost)).toBe(false);
});

test("a single non-loopback listener is refused", () => {
  expect(
    hasOnlyLoopbackAddresses({ lo: [iface("127.0.0.1", true)], wlan0: [iface("192.168.1.20", false)] }),
  ).toBe(false);
});

test("an empty interface listing is refused (fail closed)", () => {
  expect(hasOnlyLoopbackAddresses({})).toBe(false);
});

test("missing or non-string addresses are refused", () => {
  expect(
    hasOnlyLoopbackAddresses({ lo: [iface(null, true)] }),
  ).toBe(false);
  expect(
    hasOnlyLoopbackAddresses({ lo: [iface("127.0.0.1", null)] }),
  ).toBe(true);
});

test("a loopback-only listing passes the tripwire (not proof of isolation)", () => {
  expect(
    hasOnlyLoopbackAddresses({ lo: [iface("127.0.0.1", true), iface("::1", true)] }),
  ).toBe(true);
});

test("this host's real verdict is reported, never trusted blindly", () => {
  const verdict = loopbackInterfacesVerdict();
  // On a normal dev host this is false (tripwire refusal path); in a
  // loopback-only container it is true. Either way the verdict shape is
  // explicit — and a `true` here still proves no isolation.
  expect(typeof verdict.ok).toBe("boolean");
  expect(verdict.detail.length).toBeGreaterThan(0);
  if (!verdict.ok) {
    expect(() => requireLoopbackOnlyInterfaces()).toThrow(/refusing owner-journey execution/);
  }
});
