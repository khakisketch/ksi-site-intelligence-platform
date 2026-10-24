"use client";

import { useRouter } from "next/navigation";
import { createPortal } from "react-dom";
import { useSyncExternalStore, type ReactNode } from "react";

/**
 * 작업환경 무대 위 간결 매체 상태 — 어두운 중립 면에 짧은 사유와 하나의 1차
 * 회복만 둔다. 순수 배치·표현만 맡으며, 조회·판정·바이트·준비 알고리즘을
 * 바꾸지 않는다.
 *
 * - 어두움은 매체(사진·차단·읽는 중) 어휘이며, 빈 프롬프트·일반 안내는
 *   밝은 면에 둔다. 차단된 자리와 준비된 빈자리가 같은 빈 사각형으로
 *   읽히지 않게 사유+회복을 항상 함께 둔다.
 * - 높이는 의도적으로 묶는다 — 390px 폭에서도 1차 회복이 접힘 위로
 *   올라오게 `min-h-48`을 넘지 않는다. 가짜 지도·사진·기본 불러옴 상태는
 *   두지 않는다.
 * - 같은 사유의 회복은 호출자가 하나로 모아 이 자리에 한 번만 둔다. 서로
 *   다른 칸 실패는 각자 정직하게 둔다.
 *
 * Invariants: INV-020(표현 전용)/INV-040(예시 바이트 fallback 없음)/
 * INV-060·061(읽기·새로고침만 — 새 준비·권한 변경 없음).
 */
export function WorkbenchMediaState({
  headline,
  detail = null,
  hint = null,
  action = null,
  compact = false,
  alert = false,
}: {
  /** 짧은 사유 한 줄 — 무엇이 막혔는지. */
  headline: string;
  /** 덧붙일 한 줄 — 없으면 생략한다. */
  detail?: ReactNode;
  /** 희미한 한 줄 — 권한 요청처 등 사람 행동 안내. */
  hint?: ReactNode;
  /** 하나의 1차 회복(단추 또는 링크) — 호출자가 하나로 모아 둔다. */
  action?: ReactNode;
  /** true면 높이를 묶지 않고 한 줄 행으로 둔다(공유 회복 막대용). */
  compact?: boolean;
  /** true면 role="alert" — 실패 공지에만 쓴다. */
  alert?: boolean;
}) {
  return (
    <div
      role={alert ? "alert" : "status"}
      className={
        compact
          ? "flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg bg-sidebar px-4 py-3"
          : "flex min-h-48 min-w-0 flex-col items-center justify-center gap-1.5 rounded-lg bg-sidebar px-4 py-8 text-center"
      }
    >
      <p className={compact ? "min-w-0 flex-1 break-words text-[12.5px] font-bold text-sidebar-text" : "max-w-prose break-words text-[13px] font-bold text-sidebar-text"}>
        {headline}
      </p>
      {detail && (
        <p className={compact ? "min-w-0 basis-full break-words text-[12px] leading-5 text-sidebar-muted" : "max-w-prose break-words text-[12px] leading-5 text-sidebar-muted"}>
          {detail}
        </p>
      )}
      {action && <div className={compact ? "shrink-0" : "mt-1.5"}>{action}</div>}
      {hint && (
        <p className={compact ? "min-w-0 basis-full break-words text-[11.5px] leading-5 text-sidebar-muted" : "max-w-prose break-words text-[11.5px] leading-5 text-sidebar-muted"}>
          {hint}
        </p>
      )}
    </div>
  );
}

/**
 * 읽기 전용 1차 회복 — 같은 URL을 새로고침한다. 새 준비 요청·권한 변경·
 * 바이트 쓰기를 만들지 않는다.
 */
export function WorkbenchRefreshButton({
  label = "준비 상태 다시 확인",
}: {
  label?: string;
}) {
  const router = useRouter();
  return (
    <button
      type="button"
      className="btn min-h-11 border-white/25 bg-sidebar-active font-semibold text-sidebar-active-ink"
      onClick={() => router.refresh()}
    >
      {label}
    </button>
  );
}

/**
 * 정보 서랍 안 항상-마운트 자리로 접힌 상세를 옮기는 포털.
 *
 * - 자리는 서랍이 닫혀도 마운트를 유지하므로, 포털이 사라지거나 카메라·
 *   선택이 흔들리지 않는다. 닫힘 상태의 자리는 display:none이라 초점이 새지 않는다.
 * - 자리가 아직 없으면(첫 커밋 전) 렌더를 미룬다 — 무대에 펼침 벽을 두지 않는다.
 * - `targetId`가 없으면(작업환경 밖 호출) 자식을 그대로 둔다 — 기존 자리 펼침을 유지한다.
 */
export function DetailsPortal({
  targetId,
  children,
}: {
  /** 정보 서랍 안 숨김 자리 식별자. 없으면 포털 없이 자식을 그대로 둔다. */
  targetId?: string | null;
  children: ReactNode;
}) {
  const host = useSyncExternalStore(
    (notify) => {
      if (!targetId || typeof document === "undefined") return () => {};
      if (document.getElementById(targetId)) return () => {};
      const observer = new MutationObserver(() => {
        if (document.getElementById(targetId)) {
          observer.disconnect();
          notify();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
      return () => observer.disconnect();
    },
    () => (targetId && typeof document !== "undefined" ? document.getElementById(targetId) : null),
    () => null,
  );
  if (!targetId) return <>{children}</>;
  if (!host) return null;
  return createPortal(children, host);
}
