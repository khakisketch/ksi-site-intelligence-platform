import { formatNetVolumeM3 } from "@/lib/core-api/phase34-labels";
import type { ZoneVolumeDelta } from "@/lib/core-api/types";

/**
 * 구역별 순변화 막대(Console v2 §3) — "어느 구역이 얼마나 달라졌나"를 한눈에.
 *
 * ── 왜 순변화 하나만 그리나 ──────────────────────────────────────────────
 * 절토·성토를 각각 막대로 그리면 구역마다 막대가 둘이라 훑기 어렵고, 무엇보다
 * **부호가 사라진다**: 이 화면의 질문은 "여기가 쌓였나 깎였나"인데 두 막대는 그
 * 답을 독자가 암산하게 만든다. 서버가 계약으로 검증한 `netM3` 하나로만 말하고
 * (합산 규칙을 화면에서 다시 만들지 않는다), 절토·성토 원값은 임무 화면의
 * `VolumeChangeSummary` 가 이미 구역마다 보여준다.
 *
 * 막대 길이는 **이 목록 안에서의 상대 크기**다 — 절대 축이 아니다. 그래서 숫자를
 * 항상 옆에 붙인다: 막대만 보고 크기를 읽으면 다른 조사와 비교할 때 틀린다.
 *
 * ── 한계를 숨기지 않는다 ─────────────────────────────────────────────────
 * `uncertaintyM3` 가 null 인 구역은 그 사실을 세지 않고 넘어가는 대신 목록 아래
 * 한 줄로 말한다(INV-024). 기본 엔진에는 검사점 리포트가 없어 지금은 항상 null 이라,
 * 이 줄이 빠지면 화면이 "이 숫자는 검증된 값"이라 말하는 것과 같다.
 */
export function ZoneVolumeBars({
  zones,
  computedNote,
}: {
  zones: readonly ZoneVolumeDelta[];
  /** 언제·무슨 기준으로 잰 값인지 — 호출부가 서버 값에서 만들어 넘긴다. */
  computedNote?: string;
}) {
  if (zones.length === 0) {
    return (
      <p className="px-4 py-4 text-[12.5px] break-keep text-ink-2">
        계산된 구역별 물량이 없습니다.
      </p>
    );
  }

  const maxAbs = Math.max(...zones.map((zone) => Math.abs(zone.netM3)), 1);
  const withoutUncertainty = zones.filter((zone) => zone.uncertaintyM3 === null);

  return (
    <div className="flex flex-col gap-1.5 px-4 py-3">
      {zones.map((zone) => {
        const ratio = Math.abs(zone.netM3) / maxAbs;
        const width = `${Math.max(ratio * 50, 1)}%`;
        const positive = zone.netM3 >= 0;
        return (
          <div
            key={zone.zoneId}
            className="grid grid-cols-[minmax(64px,84px)_minmax(0,1fr)_92px] items-center gap-2.5"
          >
            <span className="num truncate text-[12px] font-semibold">{zone.zoneId}</span>
            {/* 가운데 선이 0 이다 — 왼쪽이 깎임, 오른쪽이 쌓임. 부호를 길이로도 말한다. */}
            <span className="relative h-4 overflow-hidden rounded-sm bg-sunk">
              <span
                aria-hidden="true"
                className="absolute inset-y-0 left-1/2 w-px bg-line-strong"
              />
              <span
                className={`absolute inset-y-0 rounded-sm ${positive ? "bg-mid" : "bg-high"}`}
                style={positive ? { left: "50%", width } : { right: "50%", width }}
              />
            </span>
            <span className="num text-right text-[12px] font-bold whitespace-nowrap">
              {formatNetVolumeM3(zone.netM3)}
            </span>
          </div>
        );
      })}

      {computedNote && (
        <p className="mt-1 text-[11px] break-keep text-ink-muted">{computedNote}</p>
      )}
      {withoutUncertainty.length > 0 && (
        <p className="text-[11px] break-keep text-ink-muted">
          구역 {withoutUncertainty.length}곳은 오차 범위가 계산되지 않았습니다 — 이 값은 상대
          변화이고, 정산 물량은 측량 성과와 대조한 뒤 확정하세요.
        </p>
      )}
    </div>
  );
}
