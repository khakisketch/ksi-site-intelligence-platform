import type { DetailsHTMLAttributes, ReactNode } from "react";

type DisclosureProps = Omit<DetailsHTMLAttributes<HTMLDetailsElement>, "children"> & {
  label: ReactNode;
  children: ReactNode;
  summaryClassName?: string;
};

export function Disclosure({
  label,
  children,
  className,
  summaryClassName,
  ...props
}: DisclosureProps) {
  return (
    <details {...props} className={`disclosure ${className ?? ""}`}>
      <summary className={`disclosure-summary tap-target ${summaryClassName ?? ""}`}>
        <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className="disclosure-chevron size-3 shrink-0">
          <path d="m4 6 4 4 4-4" />
        </svg>
        <span className="min-w-0">{label}</span>
      </summary>
      {children}
    </details>
  );
}
