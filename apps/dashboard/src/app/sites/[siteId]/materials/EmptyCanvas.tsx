import type { ReactNode } from "react";
import { RegistrationPath } from "@/components/site/RegistrationPath";

export function EmptyCanvas({ title, reason, action }: {
  title: string;
  reason: string;
  action?: ReactNode;
}) {
  return <div className="console-stage-empty viewer-canvas-empty">
    <section className="viewer-canvas-card">
      <h3 className="break-keep text-title font-bold">{title}</h3>
      <p className="max-w-sm break-keep text-body text-ink-2">{reason}</p>
      <RegistrationPath className="mt-2" />
      {action && <div className="mt-2">{action}</div>}
    </section>
  </div>;
}
