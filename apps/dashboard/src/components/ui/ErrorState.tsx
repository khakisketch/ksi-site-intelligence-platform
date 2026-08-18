"use client";

// UX 목표 §3.4 — "503 STORE_UNAVAILABLE: '서버 저장소 점검 중, 잠시 후 다시 시도'
// + 재시도 버튼(Retry-After 존중)". 문구는 labels.ts 에 있었지만 **버튼이 갈 자리가
// 없었다** — 읽기 경로의 모든 오류가 이 컴포넌트로 렌더되는데 액션 슬롯이 없어서
// 운영자가 할 수 있는 일이 새로고침(F5)뿐이었다.
//
// 재시도는 클라이언트 라우터 새로고침이다. 전체 리로드와 달리 스크롤·입력 상태를 잃지
// 않고 서버 컴포넌트만 다시 가져오므로, 일시적 5xx 에는 이쪽이 맞다.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

/** 오류의 성격별 표면색 — states 규격(Console v2 §10)의 에러 6종 정비분.
 *
 *  crit(기본)=장애·거부, high=권한·충돌처럼 "재시도가 답이 아닌" 상태,
 *  idle=없음(404)처럼 잘못도 장애도 아닌 상태. 색은 안전 상태에만 쓴다는 규칙과
 *  일치한다 — 여기서 색은 장식이 아니라 "다음 행동이 무엇인가"의 신호다.
 */
const TONE_CLASS = {
  crit: "border-crit/30 bg-crit-bg text-crit-ink",
  high: "border-high/30 bg-high-bg text-high-ink",
  idle: "border-line bg-sunk text-ink-2",
} as const;

export function ErrorState({
  message,
  detail,
  retryable = false,
  /** Retry-After(초). 서버가 언제 돌아올지 말해줬다면 그 전에는 누르게 두지 않는다. */
  retryAfterSeconds,
  tone = "crit",
  /** 재시도가 답이 아닌 오류의 탈출구(예: 403 → 권한 안내, 404 → 목록으로).
   *  retryable 과 함께 줄 수도 있다 — 401 처럼 "다시 로그인" 링크가 답인 자리. */
  action,
}: {
  message: string;
  detail?: string;
  retryable?: boolean;
  retryAfterSeconds?: number;
  tone?: keyof typeof TONE_CLASS;
  action?: { label: string; href: string };
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
      className={`flex flex-col items-start gap-2 rounded-lg border px-4 py-3 text-[13px] ${TONE_CLASS[tone]}`}
    >
      <p className="font-semibold break-keep">{message}</p>
      {detail && <p className="break-keep opacity-80">{detail}</p>}
      {action && (
        <Link href={action.href} className="btn mt-1 bg-surface">
          {action.label}
        </Link>
      )}
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
