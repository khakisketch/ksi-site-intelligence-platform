"use client";

import { useEffect, useRef } from "react";

export function SelectedAssetHeading({ assetRef, title }: { assetRef: string; title: string }) {
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (window.location.hash !== "#section-inspector" || window.matchMedia("(min-width: 1280px)").matches) return;
    const target = heading.current;
    const panel = target?.closest<HTMLElement>("#section-inspector");
    if (!target || !panel) return;
    // A streamed inspector can be mounted while the account display is still hidden.
    const observer = new ResizeObserver(() => {
      if (!panel.getClientRects().length) return;
      observer.disconnect();
      if (window.location.hash !== "#section-inspector") return;
      target.focus({ preventScroll: true });
      panel.scrollIntoView({ block: "start" });
    });
    observer.observe(panel);
    return () => observer.disconnect();
  }, [assetRef]);

  return <h3 ref={heading} tabIndex={-1} className="break-words text-lead font-bold text-ink-1">{title}</h3>;
}
