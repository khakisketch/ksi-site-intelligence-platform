import type { EquipmentStateItem } from "@/lib/core-api/types";

export interface WorldFreshnessSummary {
  latestObservedAt: string | null;
  latestRecordedAt: string | null;
  oldestObservedAt: string | null;
  clockSkewCount: number;
  reportingDeviceCount: number;
}

function latest(items: string[]): string | null {
  if (items.length === 0) return null;
  return items.reduce((current, candidate) =>
    new Date(candidate).getTime() > new Date(current).getTime() ? candidate : current,
  );
}

function oldest(items: string[]): string | null {
  if (items.length === 0) return null;
  return items.reduce((current, candidate) =>
    new Date(candidate).getTime() < new Date(current).getTime() ? candidate : current,
  );
}

/**
 * World 데이터 최신성 요약.
 *
 * "온라인"이나 "실시간"을 추론하지 않는다. 운동상태 API는 heartbeat가 아니라
 * 관측 원장이므로 화면이 확실히 말할 수 있는 것은 센서 관측 시각, Core 기록 시각,
 * 신고 장비뿐이다. 연결 상태는 Fleet용 heartbeat 계약이 생길 때까지 별도다.
 */
export function summarizeWorldFreshness(
  entities: EquipmentStateItem[],
  nowMs: number,
): WorldFreshnessSummary {
  const observed = entities.map((item) => item.state.observedAt);
  const recorded = entities.map((item) => item.recordedAt);
  return {
    latestObservedAt: latest(observed),
    latestRecordedAt: latest(recorded),
    oldestObservedAt: oldest(observed),
    clockSkewCount: observed.filter((value) => new Date(value).getTime() > nowMs).length,
    reportingDeviceCount: new Set(
      entities.map((item) => item.reportedBy).filter((value): value is string => Boolean(value)),
    ).size,
  };
}

/** 임의 fresh/stale 문턱 없이 관측 경과만 표시한다. */
export function formatObservationAge(iso: string, nowMs: number): string {
  const observedMs = new Date(iso).getTime();
  if (Number.isNaN(observedMs)) return "시각 형식 오류";
  const elapsedSeconds = Math.floor((nowMs - observedMs) / 1000);
  if (elapsedSeconds < 0) return "미래 시각 — 장비 시계 확인 필요";
  if (elapsedSeconds < 60) return `${elapsedSeconds}초 전`;
  const elapsedMinutes = Math.floor(elapsedSeconds / 60);
  if (elapsedMinutes < 60) return `${elapsedMinutes}분 전`;
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) return `${elapsedHours}시간 전`;
  return `${Math.floor(elapsedHours / 24)}일 전`;
}
