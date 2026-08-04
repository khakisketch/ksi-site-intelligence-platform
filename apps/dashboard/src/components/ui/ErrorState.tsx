"use client";

// UX 목표 §3.4 — "503 STORE_UNAVAILABLE: '서버 저장소 점검 중, 잠시 후 다시 시도'
// + 재시도 버튼(Retry-After 존중)". 문구는 labels.ts 에 있었지만 **버튼이 갈 자리가
// 없었다** — 읽기 경로의 모든 오류가 이 컴포넌트로 렌더되는데 액션 슬롯이 없어서
// 운영자가 할 수 있는 일이 새로고침(F5)뿐이었다.
//
// 재시도는 클라이언트 라우터 새로고침이다. 전체 리로드와 달리 스크롤·입력 상태를 잃지
// 않고 서버 컴포넌트만 다시 가져오므로, 일시적 5xx 에는 이쪽이 맞다.
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

export function ErrorState({
  message,
  detail,
  retryable = false,
  /** Retry-After(초). 서버가 언제 돌아올지 말해줬다면 그 전에는 누르게 두지 않는다. */
  retryAfterSeconds,
}: {
  message: string;
  detail?: string;
  retryable?: boolean;
  retryAfterSeconds?: number;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [waitLeft, setWaitLeft] = useState(retryAfterSeconds ?? 0);

  useEffect(() => {
    if (waitLeft <= 0) return;
    const id = setTimeout(() => setWaitLeft((n) => n - 1), 1000);
    return () => clearTimeout(id);
  }, [waitLeft]);

  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-2 rounded-lg border border-crit/30 bg-crit-bg px-4 py-3 text-[13px] text-crit-ink"
    >
      <p className="font-semibold break-keep">{message}</p>
      {detail && <p className="text-crit-ink/80 break-keep">{detail}</p>}
      {retryable && (
        <button
          type="button"
          disabled={waitLeft > 0 || isPending}
          onClick={() => startTransition(() => router.refresh())}
          className="btn btn-danger mt-1 bg-surface"
        >
          {isPending
            ? "다시 시도하는 중…"
            : waitLeft > 0
              ? `${waitLeft}초 후 다시 시도`
              : "다시 시도"}
        </button>
      )}
    </div>
  );
}
