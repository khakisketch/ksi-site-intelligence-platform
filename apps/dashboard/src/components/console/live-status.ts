/** 라이브 수신 표시의 문구·상태 판정 — 순수 함수.
 *
 * 디자인 근거: `KSI Console v2.dc.html` §0 상단바 — "마지막 수신 12초 전",
 * 오프라인이면 `var(--crit)`.
 *
 * **이 표시가 거짓말을 하지 않는 것이 요건이다**(INV-040). "라이브"라고 적어 놓고
 * 실제로는 갱신이 끊긴 화면은, 사용자가 낡은 숫자를 최신으로 읽게 만든다 — 그건
 * 빈 화면보다 나쁘다. 그래서 상태가 셋이다: 수신 중 · 지연 · 끊김.
 */

export type LiveTone = "live" | "stale" | "offline";

/** 마지막 수신 이후 이 시간을 넘으면 "지연"으로 강등한다(초). */
export const STALE_AFTER_S = 30;
/** 이 시간을 넘으면 "끊김"으로 본다(초). */
export const OFFLINE_AFTER_S = 120;

export interface LiveStatus {
  tone: LiveTone;
  /** 상단바에 그대로 들어가는 문구. */
  label: string;
  /** 점 색 토큰 — 화면 코드가 색을 직접 고르지 않게 여기서 준다. */
  dotClass: string;
  /** 맥동 애니메이션을 돌릴지. 끊긴 상태에서 맥동하면 살아 있는 것처럼 보인다. */
  pulse: boolean;
}

function elapsedLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}초 전`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  return `${hours}시간 전`;
}

/**
 * @param elapsedSeconds 마지막 수신 이후 경과 초. 음수는 0 으로 본다(시계 역행 방어).
 * @param paused 사용자가 라이브 갱신을 껐는가 — 끊김과 구분해서 보여준다.
 */
export function resolveLiveStatus(elapsedSeconds: number, paused = false): LiveStatus {
  const elapsed = Math.max(0, Math.floor(elapsedSeconds));

  if (paused) {
    return {
      tone: "stale",
      label: "실시간 갱신 꺼짐",
      dotClass: "bg-idle",
      pulse: false,
    };
  }
  if (elapsed >= OFFLINE_AFTER_S) {
    return {
      tone: "offline",
      // 끊긴 시점을 함께 밝힌다 — "끊김"만 있으면 언제부터인지 몰라 판단이 안 선다.
      label: `수신 끊김 · 마지막 ${elapsedLabel(elapsed)}`,
      dotClass: "bg-crit",
      pulse: false,
    };
  }
  if (elapsed >= STALE_AFTER_S) {
    return {
      tone: "stale",
      label: `마지막 수신 ${elapsedLabel(elapsed)}`,
      dotClass: "bg-high",
      pulse: false,
    };
  }
  return {
    tone: "live",
    label: `마지막 수신 ${elapsedLabel(elapsed)}`,
    dotClass: "bg-safe",
    pulse: true,
  };
}
