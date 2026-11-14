import type { ReactNode } from "react";

export function SiteLayerDisclosure({ children }: { children: ReactNode }) {
  return (
    <section className="min-w-0 border-t border-line pt-2">
      <h3 className="text-caption font-semibold">표시 레이어</h3>
      <div className="mt-2 min-w-0">{children}</div>
    </section>
  );
}
