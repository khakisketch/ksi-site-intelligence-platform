import type { ReactNode } from "react";

export function OperationsWorkHeader({ children }: { children: ReactNode }) {
  return (
    <header className="flex flex-col gap-2 border-b border-line px-4 py-4 lg:px-5">
      {children}
    </header>
  );
}
