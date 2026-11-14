import type { ReactNode } from "react";

/** Top-level container for list/form screens. */
export function ConsolePage({
  children,
  density = "regular",
  className = "",
}: {
  children: ReactNode;
  density?: "regular" | "dense";
  className?: string;
}) {
  return <div className={`console-page${density === "dense" ? " console-page-dense" : ""} ${className}`.trim()}>{children}</div>;
}

/** Reusable section rhythm; not a card, so information hierarchy stays explicit. */
export function ConsolePageSection({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`console-page-section ${className}`.trim()}>{children}</section>;
}

/** Workspace shell that occupies available content height without introducing scroll. */
export function ConsoleWork({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`console-work ${className}`.trim()}>{children}</div>;
}

/** A stable visual stage for maps, comparisons and empty/loading content. */
export function ConsoleStage({
  children,
  empty = false,
  className = "",
}: {
  children: ReactNode;
  empty?: boolean;
  className?: string;
}) {
  return <div className={`${empty ? "console-stage-empty" : "console-stage"} ${className}`.trim()}>{children}</div>;
}
