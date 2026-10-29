import { networkInterfaces } from "node:os";

// Test-only network-boundary helpers for the owner-journey synthetic probe.
// No browser, no network, no mutation: pure predicates over OS interface data
// plus a fail-closed tripwire used before any navigation/mutation.
//
// LIMITATION (integration boundary): observing loopback-only addresses here
// proves NEITHER Docker `--network none` NOR external egress impossibility —
// address-less interfaces, route changes, UNIX sockets, and local forwarding
// services are unverified by this module. Passing this check confirms no OS
// isolation and infers no ownership of arbitrary local services. Actual
// reproduction happens ONLY in a network-isolated task-owned container,
// established by the operator — never self-proved by a product test.

/** Loopback hostnames. Node reports IPv6 loopback WITH brackets (`[::1]`). */
export function isLoopbackHostname(hostname: string): boolean {
  const bare =
    hostname.startsWith("[") && hostname.endsWith("]")
      ? hostname.slice(1, -1)
      : hostname;
  return bare === "127.0.0.1" || bare === "localhost" || bare === "::1";
}

export type InterfaceAddress = {
  address?: string | null;
  internal?: boolean | null;
};

/**
 * True only when every reported address is loopback. Zero addresses is NOT
 * accepted (fail closed: an empty listing is not a verified loopback-only
 * host). Takes the interface table as input so the logic itself is unit
 * testable without touching the real host (see zz-owner-journey-refusal).
 */
export function hasOnlyLoopbackAddresses(
  interfaces: NodeJS.Dict<InterfaceAddress[]>,
): boolean {
  const addresses = Object.values(interfaces)
    .flat()
    .filter((entry) => entry !== undefined && entry !== null);
  if (addresses.length === 0) return false;
  return addresses.every(
    (entry) =>
      typeof entry.address === "string" &&
      (entry.internal === true || isLoopbackHostname(entry.address)),
  );
}

export type LoopbackCheckVerdict = {
  ok: boolean;
  detail: string;
};

/** Read the real host's interfaces and judge loopback-only status. */
export function loopbackInterfacesVerdict(): LoopbackCheckVerdict {
  const interfaces = networkInterfaces();
  const names = Object.keys(interfaces).sort().join(",");
  if (hasOnlyLoopbackAddresses(interfaces)) {
    return { ok: true, detail: `loopback-only interfaces: ${names || "(none)"}` };
  }
  return { ok: false, detail: `non-loopback interface present: ${names}` };
}

/**
 * Fail-closed tripwire: refuse to proceed unless the CURRENT host exposes
 * loopback interfaces only. This is a measurement of the actual OS, not an
 * environment-variable attestation — caller env is never trusted for this
 * decision. It is NOT proof of isolation: it says nothing about egress,
 * address-less interfaces, routes, UNIX sockets, or who owns any local
 * service. Call before any page navigation or mutation; actual reproduction
 * belongs in a network-isolated task-owned container.
 */
export function requireLoopbackOnlyInterfaces(): void {
  const verdict = loopbackInterfacesVerdict();
  if (!verdict.ok) {
    throw new Error(
      `refusing owner-journey execution: ${verdict.detail}; ` +
        "this mutating probe reproduces only in a network-isolated " +
        "task-owned container. This check alone proves no isolation and " +
        "infers no ownership of local services.",
    );
  }
}
