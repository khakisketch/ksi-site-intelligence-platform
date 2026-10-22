"use client";

import { useState, useSyncExternalStore, type ReactNode } from "react";

const desktopQuery = "(min-width: 1024px)";
const serverSnapshot = () => false;
const desktopSnapshot = () => typeof window.matchMedia === "function" && window.matchMedia(desktopQuery).matches;
function subscribe(onChange: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(desktopQuery);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/** One native disclosure and one set of portal destinations; exposed state stays truthful. */
export function SiteLayerDisclosure({ children }: { children: ReactNode }) {
  const desktop = useSyncExternalStore(subscribe, desktopSnapshot, serverSnapshot);
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? desktop;
  return <details open={open} className="min-w-0 border-t border-line pt-2">
    <summary className="tap-target cursor-pointer text-[12px] font-semibold" onClick={(event) => {
      event.preventDefault();
      setUserOpen(!open);
    }}><h3 className="inline">표시 레이어</h3></summary>
    <div className="mt-2 min-w-0">{children}</div>
  </details>;
}
