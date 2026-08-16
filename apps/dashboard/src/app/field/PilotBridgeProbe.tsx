"use client";

import { useSyncExternalStore } from "react";

// 조종기 웹뷰 진단 — **표시만 한다.**
//
// DJI Pilot 2 의 서드파티 클라우드 웹뷰는 `window.djiBridge` 를 주입한다고 알려져
// 있지만, 우리는 그 객체가 M4D + Pilot 2 조합에서 실제로 무엇을 갖는지 **재본 적이
// 없다**(FIELD-0b U9). 그래서 이 컴포넌트는 값을 읽어 보여줄 뿐, 어떤 화면 동작도
// 이 값에 걸지 않는다(ADR-KSI-017 §3 — MSDK 경로를 채택하지 않는다는 결정의 실무
// 표현). 브리지가 있으면 켜지는 기능을 하나라도 만드는 순간, 그 기능은 현장에서
// 브라우저로 열었을 때 조용히 사라진다.
//
// 이 화면의 쓸모는 하나다: 현장에서 U9 를 잴 때 **키 목록을 눈으로 읽어 적을 수
// 있다**. 그래서 접힌 채로 두되 지우지는 않는다.

type ProbeResult =
  | { kind: "checking" }
  | { kind: "absent" }
  | { kind: "present"; type: string; keys: string[] };

/**
 * 브리지 객체의 키를 모은다.
 *
 * `Object.keys` 만으로는 부족하다 — 네이티브 브리지는 메서드를 프로토타입에 두거나
 * 열거 불가로 정의하는 경우가 흔해서 빈 배열이 나오고, 그러면 "브리지는 있는데
 * 아무것도 없다"는 **틀린** 관찰을 적게 된다. 소유 속성·상속 열거 속성·프로토타입
 * 속성을 모두 훑고, 열거 자체가 던지면(Proxy) 그 사실만 남긴다.
 */
function collectBridgeKeys(bridge: object): string[] {
  const found = new Set<string>();
  try {
    for (const key in bridge) found.add(key);
    for (const key of Object.getOwnPropertyNames(bridge)) found.add(key);
    const proto: unknown = Object.getPrototypeOf(bridge);
    if (proto && proto !== Object.prototype) {
      for (const key of Object.getOwnPropertyNames(proto as object)) found.add(key);
    }
  } catch {
    return ["(키를 열거할 수 없습니다)"];
  }
  found.delete("constructor");
  return [...found].sort();
}

function probeBridge(): ProbeResult {
  const bridge = (window as unknown as { djiBridge?: unknown }).djiBridge;
  if (bridge === undefined || bridge === null) return { kind: "absent" };
  const type = typeof bridge;
  // 원시값이 주입되는 경우도 배제하지 않는다 — 지어내지 않고 본 대로 적는다.
  if (type !== "object" && type !== "function") return { kind: "present", type, keys: [] };
  return { kind: "present", type, keys: collectBridgeKeys(bridge as object) };
}

// ── 왜 useEffect + setState 가 아니라 useSyncExternalStore 인가 ──────────────
// `window.djiBridge` 는 React 밖의 값이고, 서버에는 존재하지 않는다. effect 안에서
// setState 로 읽으면 첫 렌더가 반드시 버려지는 연쇄 렌더가 된다(react-hooks/
// set-state-in-effect 가 잡는 것이 정확히 그것이다). 이 훅은 "서버 스냅샷"과
// "클라이언트 스냅샷"을 따로 받도록 만들어져 있어 hydration 불일치 없이 한 번에
// 전환된다.
//
// 스냅샷은 모듈 수준에서 한 번만 계산해 캐시한다. 두 가지 이유가 있다:
// ① `useSyncExternalStore` 는 getSnapshot 을 여러 번 부르고 Object.is 로 비교한다 —
//    매번 새 객체를 만들면 값이 같아도 다르다고 판정돼 무한 렌더가 된다.
// ② 브리지 주입은 문서 로드 시점에 끝난다. 매번 다시 훑을 이유가 없다.
let cachedSnapshot: ProbeResult | null = null;

function getSnapshot(): ProbeResult {
  cachedSnapshot ??= probeBridge();
  return cachedSnapshot;
}

// 서버에는 window 가 없다 — 모른다고 말하는 것이 서버가 아는 전부다.
const SERVER_SNAPSHOT: ProbeResult = { kind: "checking" };
function getServerSnapshot(): ProbeResult {
  return SERVER_SNAPSHOT;
}

// 브리지는 바뀌지 않는다 — 구독할 것이 없다(해지 함수도 아무 일도 하지 않는다).
// 모듈 수준 상수여야 렌더마다 재구독하지 않는다.
const NO_OP_UNSUBSCRIBE = () => {};
const subscribe = () => NO_OP_UNSUBSCRIBE;

export function PilotBridgeProbe() {
  const result = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const summary =
    result.kind === "checking"
      ? "확인 중…"
      : result.kind === "absent"
        ? "없음 (일반 브라우저로 열렸습니다)"
        : `있음 · ${result.type} · 키 ${result.keys.length}개`;

  return (
    <details className="rounded-lg border border-line bg-surface">
      <summary className="tap-target flex min-h-11 cursor-pointer items-center px-4 text-[13px] break-keep text-ink-2">
        조종기 브리지 진단 — {summary}
      </summary>
      <div className="flex flex-col gap-2 border-t border-line px-4 py-3">
        <p className="text-[12.5px] break-keep text-ink-muted">
          이 화면의 어떤 동작도 이 값에 의존하지 않습니다. 조종기에서 열었는지 확인하고
          키 이름을 기록하기 위한 표시일 뿐입니다.
        </p>
        {result.kind === "present" && result.keys.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">
            {result.keys.map((key) => (
              <li
                key={key}
                className="num rounded-[4px] border border-line bg-sunk px-1.5 py-0.5 text-[11px] break-token text-ink-2"
              >
                {key}
              </li>
            ))}
          </ul>
        )}
        {result.kind === "present" && result.keys.length === 0 && (
          <p className="text-[12.5px] break-keep text-ink-2">
            객체는 있지만 읽어낼 수 있는 키가 없습니다.
          </p>
        )}
      </div>
    </details>
  );
}
