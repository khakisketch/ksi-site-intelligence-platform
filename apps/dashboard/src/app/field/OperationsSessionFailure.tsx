import { redirect } from "next/navigation";

import { ErrorState } from "@/components/ui/ErrorState";

import type { FieldSessionVerdict } from "./field-session";

export function OperationsSessionFailure({
  verdict,
  next,
}: {
  verdict: FieldSessionVerdict;
  next: string;
}) {
  if (verdict.kind === "login") {
    const params = new URLSearchParams({ next });
    if (verdict.notice) params.set("notice", verdict.notice);
    redirect(`/login?${params.toString()}`);
  }

  return (
    <div className="p-4 lg:p-5">
      <ErrorState message={verdict.message} retryable />
    </div>
  );
}
