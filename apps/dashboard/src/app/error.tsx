"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/ui/ErrorState";

// Next.js 16: 두 번째 인자가 reset 이 아니라 unstable_retry 다(node_modules/next/dist/docs 확인).
export default function RootError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-col items-start gap-3 p-6">
      <ErrorState message="예상치 못한 오류가 발생했습니다." detail={error.digest ? undefined : error.message} />
      <button
        type="button"
        onClick={() => unstable_retry()}
        className="border-foreground/30 min-h-11 rounded-md border px-4 text-sm"
      >
        다시 시도
      </button>
    </div>
  );
}
