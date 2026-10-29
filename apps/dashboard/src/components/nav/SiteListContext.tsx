"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useAccountDisplayLock } from "./AccountDisplayBoundary";
import { parseShellSites } from "./shell-site-validation";
import type { SidebarSite } from "./site-context";

type RefreshState = "idle" | "pending" | "error";
type Snapshot = { sites: readonly SidebarSite[]; refreshed: boolean; state: RefreshState; refresh: (siteId?: string) => Promise<void> };
const SiteListContext = createContext<Snapshot | null>(null);
const REFRESH_DEADLINE_MS = 10_000;

export function SiteListProvider({ sites, fingerprint = null, children }: { sites: readonly SidebarSite[]; fingerprint?: string | null; children: ReactNode }) {
  const account = useAccountDisplayLock();
  const [updated, setUpdated] = useState<readonly SidebarSite[] | null>(null);
  const [state, setState] = useState<RefreshState>("idle");
  const sequence = useRef(0);
  const target = useRef<string | null>(null);
  const activeGeneration = useRef<number | null>(null);
  const activeAttempt = useRef<{ cancel: () => void } | null>(null);
  useEffect(() => () => { sequence.current++; activeAttempt.current?.cancel(); }, []);
  useEffect(() => {
    if (activeGeneration.current !== null && account && activeGeneration.current !== account.generation()) {
      ++sequence.current;
      activeAttempt.current?.cancel();
      activeGeneration.current = null;
      setState("error");
    }
  }, [account]);
  const refresh = useCallback(async (siteId?: string) => {
    if (siteId) target.current = siteId;
    if (!target.current || !fingerprint || !account || account.locked()) { setState("error"); return; }
    const ticket = ++sequence.current;
    activeAttempt.current?.cancel();
    const generation = account.generation();
    activeGeneration.current = generation;
    setState("pending");
    const current = () => ticket === sequence.current && generation === account.generation() && !account.locked();
    const controller = new AbortController();
    let stage: "identity" | "sites" = "identity";
    let timedOut = false;
    let cancel!: () => void;
    let timer: ReturnType<typeof setTimeout>;
    const deadline = new Promise<never>((_, reject) => {
      cancel = () => { controller.abort(); reject(new Error("canceled")); };
      timer = setTimeout(() => { timedOut = true; controller.abort(); reject(new Error("deadline")); }, REFRESH_DEADLINE_MS);
    });
    const attempt = { cancel };
    activeAttempt.current = attempt;
    const run = async () => {
      // Check before and after the read; the BFF additionally binds both Core reads to one token.
      const verify = async () => {
        stage = "identity";
        let response: Response;
        try { response = await fetch("/api/account-identity", { cache: "no-store", signal: controller.signal }); }
        catch { if (!timedOut && current()) account.invalidate(); throw new Error("identity unavailable"); }
        if (!current()) throw new Error("stale");
        if (!response.ok) { account.invalidate(); throw new Error("identity unavailable"); }
        let body: unknown;
        try { body = await response.json(); }
        catch { if (!timedOut && current()) account.invalidate(); throw new Error("identity unavailable"); }
        if (!current()) throw new Error("stale");
        if (!body || typeof body !== "object" || (body as {fingerprint?: unknown}).fingerprint !== fingerprint) {
          account.invalidate();
          throw new Error("identity changed");
        }
      };
      await verify();
      stage = "sites";
      const response = await fetch("/api/shell-sites", { cache: "no-store", signal: controller.signal, headers: { "x-ksi-continuity-fingerprint": fingerprint } });
      if (!current()) return;
      if (!response.ok) {
        if (response.status === 409 || response.status === 401) account.invalidate();
        throw new Error("site list unavailable");
      }
      const body: unknown = await response.json();
      if (!current()) return;
      if (!body || typeof body !== "object" || (body as {fingerprint?: unknown}).fingerprint !== fingerprint) throw new Error("invalid snapshot");
      const next = parseShellSites((body as {sites?: unknown}).sites);
      if (!next || !next.some(site => site.siteId === target.current)) throw new Error("site not confirmed");
      await verify();
      if (!current()) return;
      activeGeneration.current = null;
      setUpdated(next);
      setState("idle");
    };
    try {
      await Promise.race([run(), deadline]);
    } catch {
      if (ticket === sequence.current) {
        const identityStillCurrent = current();
        ++sequence.current;
        activeGeneration.current = null;
        setState("error");
        if (timedOut && stage === "identity" && identityStillCurrent) account.invalidate();
      }
    } finally {
      clearTimeout(timer!);
      if (activeAttempt.current === attempt) activeAttempt.current = null;
    }
  }, [account, fingerprint]);
  return <SiteListContext.Provider value={{ sites: updated ?? sites, refreshed: updated !== null, state, refresh }}>{children}</SiteListContext.Provider>;
}
export function useSidebarSites(): readonly SidebarSite[] { return useContext(SiteListContext)?.sites ?? []; }
export function useSiteListRefresh() { return useContext(SiteListContext)?.refresh ?? (async () => {}); }
export function useSiteListSnapshot() { return useContext(SiteListContext); }
