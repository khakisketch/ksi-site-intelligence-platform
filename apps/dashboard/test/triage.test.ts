import { describe, expect, it } from "vitest";

import {
  ackSlaMs,
  ackSlaState,
  UNCLASSIFIED_ACK_SLA_MS,
  formatElapsed,
  formatTargetDuration,
  isSettled,
  isUnattended,
  sortForTriage,
} from "@/lib/core-api/triage";
import type { EventSeverity, EventStatus, EventSummaryResponse, TriageStatus } from "@/lib/core-api/types";

// 트리아지 규칙은 "지금 사람이 봐야 하는 것"의 정의다 — 이게 조용히 바뀌면 화면은
// 멀쩡한데 위험 건이 대기열 아래로 사라진다. 회귀가 눈에 안 보이는 종류라 테스트로 고정한다.

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function event(overrides: Partial<EventSummaryResponse> = {}): EventSummaryResponse {
  return {
    eventKey: "dev-1::evt-1",
    eventId: "evt-1",
    siteId: "site-1",
    missionId: "mission-1",
    eventType: "PERSON_PRESENT",
    status: "CANDIDATE" as EventStatus,
    severity: null,
    triage: "NONE" as TriageStatus,
    assignee: null,
    edgeDeviceId: "dev-1",
    occurredAt: "2026-08-04T00:00:00Z",
    receivedAt: "2026-08-04T00:00:01Z",
    ...overrides,
  };
}

describe("방치(unattended) 판정", () => {
  it("아무도 배정받지 않았고 종단에 이르지 않았으면 방치다", () => {
    expect(isUnattended(event())).toBe(true);
  });

  it("배정되면 더 이상 방치가 아니다", () => {
    expect(isUnattended(event({ triage: "ASSIGNED" as TriageStatus }))).toBe(false);
  });

  it.each(["CONFIRMED_EVENT", "DISMISSED"] as const)(
    "종단 상태 %s 는 배정 전이라도 방치가 아니다",
    (status) => {
      expect(isUnattended(event({ status: status as EventStatus }))).toBe(false);
      expect(isSettled(event({ status: status as EventStatus }))).toBe(true);
    },
  );

  it("OBSERVATION 도 방치 대상이다 — 인지 파이프라인이 실제로 발행하는 상태다", () => {
    // 사이드바 배지가 이 상태를 빼고 세다가 홈·목록과 건수가 어긋난 이력이 있다
    // (nav-counts.ts 주석). 정의가 둘이 되면 그중 하나는 반드시 거짓말이 된다.
    expect(isUnattended(event({ status: "OBSERVATION" as EventStatus }))).toBe(true);
  });
});

describe("확인(Acknowledge) SLA", () => {
  it("심각도가 높을수록 목표가 짧다", () => {
    const critical = ackSlaMs("CRITICAL" as EventSeverity);
    const high = ackSlaMs("HIGH" as EventSeverity);
    const medium = ackSlaMs("MEDIUM" as EventSeverity);
    const candidate = ackSlaMs("CANDIDATE" as EventSeverity);
    expect(critical).toBeLessThan(high);
    expect(high).toBeLessThan(medium);
    expect(medium).toBeLessThan(candidate);
  });

  it("심각도 미판정 건에도 목표가 걸린다 — 모르는 것을 오래 두는 게 가장 위험하다", () => {
    expect(ackSlaMs(null)).toBe(UNCLASSIFIED_ACK_SLA_MS);
  });

  it("목표의 80% 를 넘기면 초과 전에 미리 due-soon 이 된다", () => {
    const target = ackSlaMs("CRITICAL" as EventSeverity);
    const critical = event({ severity: "CRITICAL" as EventSeverity });
    expect(ackSlaState(critical, target * 0.79)).toBe("ok");
    expect(ackSlaState(critical, target * 0.8)).toBe("due-soon");
    expect(ackSlaState(critical, target)).toBe("breached");
  });

  it("이미 사람이 붙은 건은 SLA 를 판정하지 않는다", () => {
    const assigned = event({ triage: "ASSIGNED" as TriageStatus });
    expect(ackSlaState(assigned, 10 * HOUR)).toBeNull();
  });
});

describe("대기열 정렬", () => {
  it("종결된 건은 아무리 오래됐어도 맨 아래다 — 대기열은 할 일이지 기록이 아니다", () => {
    const sorted = sortForTriage([
      event({ eventKey: "settled", status: "DISMISSED" as EventStatus, occurredAt: "2026-01-01T00:00:00Z" }),
      event({ eventKey: "open", occurredAt: "2026-08-04T00:00:00Z" }),
    ]);
    expect(sorted.map((e) => e.eventKey)).toEqual(["open", "settled"]);
  });

  it("CRITICAL 만 상단에 고정된다 — HIGH 는 방치 시간 순 그룹에 남는다", () => {
    // 고정 그룹이 넓어질수록 그 안에서 방치 시간이 무시된다. HIGH 까지 올리면
    // "3일 방치된 HIGH"와 "방금 들어온 HIGH"가 같은 층에 놓여, 이 화면이 막으려던
    // 실패를 다시 만든다(triage.ts sortForTriage 주석 — 정본은 sort-hybrid 연구).
    const sorted = sortForTriage([
      event({ eventKey: "old-high", severity: "HIGH" as EventSeverity, occurredAt: "2026-01-01T00:00:00Z" }),
      event({ eventKey: "new-critical", severity: "CRITICAL" as EventSeverity, occurredAt: "2026-08-04T00:00:00Z" }),
    ]);
    expect(sorted[0].eventKey).toBe("new-critical");
  });

  it("같은 층에서는 오래된 것이 위로 온다", () => {
    const sorted = sortForTriage([
      event({ eventKey: "new", occurredAt: "2026-08-04T00:00:00Z" }),
      event({ eventKey: "old", occurredAt: "2026-08-01T00:00:00Z" }),
    ]);
    expect(sorted.map((e) => e.eventKey)).toEqual(["old", "new"]);
  });

  it("입력 배열을 제자리에서 바꾸지 않는다", () => {
    const input = [event({ eventKey: "a" }), event({ eventKey: "b", occurredAt: "2026-01-01T00:00:00Z" })];
    const before = input.map((e) => e.eventKey);
    sortForTriage(input);
    expect(input.map((e) => e.eventKey)).toEqual(before);
  });
});

describe("경과 시간 표기", () => {
  it("방치 건은 '~째 미조치'로 아직 끝나지 않았음을 드러낸다", () => {
    expect(formatElapsed(3 * HOUR, { unattended: true })).toBe("3시간째 미조치");
    expect(formatElapsed(3 * HOUR, { unattended: false })).toBe("3시간 전");
  });

  it("1분 미만은 숫자를 세지 않는다", () => {
    expect(formatElapsed(30_000, { unattended: true })).toBe("방금 들어옴");
    expect(formatElapsed(30_000, { unattended: false })).toBe("방금");
  });

  it("하루 이상 방치돼도 '~일째 미조치'로 진행 중임을 드러낸다", () => {
    expect(formatElapsed(3 * DAY, { unattended: true })).toBe("3일째 미조치");
    expect(formatElapsed(3 * DAY, { unattended: false })).toBe("3일 전");
  });
});

describe("SLA 목표 시간 표기", () => {
  it("일/시간/분 단위로 반올림해 표기한다 — AckElapsedFact·DwellBar 공용", () => {
    expect(formatTargetDuration(3 * DAY)).toBe("3일");
    expect(formatTargetDuration(4 * HOUR)).toBe("4시간");
    expect(formatTargetDuration(15 * MINUTE)).toBe("15분");
  });

  it("1분 미만도 0분이 아니라 최소 1분으로 표기한다", () => {
    expect(formatTargetDuration(30_000)).toBe("1분");
  });
});
