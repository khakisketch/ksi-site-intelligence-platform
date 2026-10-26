"use client";

import { useSyncExternalStore } from "react";

const KEY = "ksi.console.desktop-nav.v1";
const CHANGE = "ksi-desktop-nav-change";
// Only changed by browser events. No user-specific server state is retained.
let fallbackCollapsed = false;

function snapshot(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "collapsed";
  } catch {
    return fallbackCollapsed;
  }
}

function serverSnapshot(): boolean {
  return false;
}

function subscribe(notify: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key === KEY || event.key === null) notify();
  };
  window.addEventListener(CHANGE, notify);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE, notify);
    window.removeEventListener("storage", onStorage);
  };
}

export function useDesktopNavCollapsed(): boolean {
  return useSyncExternalStore(subscribe, snapshot, serverSnapshot);
}

export function setDesktopNavCollapsed(collapsed: boolean) {
  fallbackCollapsed = collapsed;
  try {
    window.localStorage.setItem(KEY, collapsed ? "collapsed" : "expanded");
  } catch {
    // Storage-disabled sessions still have a working in-memory preference.
  }
  window.dispatchEvent(new Event(CHANGE));
}
