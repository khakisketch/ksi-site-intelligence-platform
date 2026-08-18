import {
  SITE_PROGRESS_STAGES,
  type SiteProgressCell,
  siteProgress,
} from "@/lib/core-api/site-progress";
import type { SiteStatus } from "@/lib/core-api/types";

// 색은 안전 상태에만 쓴다는 규칙 안에서: 지나온 단계·현재는 무채색 농담으로, 되돌아간
// 단계만 주의색을 쓴다. 되돌아감은 "앞으로 가는 중"과 헷갈리면 안 되는 사실이라 여기서만
// 색이 신호로 필요하다.
const CELL_CLASS: Record<SiteProgressCell, string> = {
  done: "bg-ink-muted",
  current: "bg-ink-1",
  rework: "bg-high",
  todo: "bg-line-strong",
  unknown: "bg-line",
};

/**
 * 진행 단계 막대(Console v2 §2) — 상태 하나를 본선 위 위치로 보여준다.
 *
 * 위치 판정은 `site-progress.ts` 가 도메인 전이표에서 가져온다. 이 컴포넌트는 그
 * 결과를 그리기만 한다 — 화면에서 순서를 다시 정의하면 두 곳이 갈라진다.
 *
 * 막대는 색만으로 말하므로 스크린리더에는 문장을 준다(색맹·저시력 고려, UX 목표 §5).
 */
export function SiteProgressBar({ status }: { status: SiteStatus }) {
  const { cells, note } = siteProgress(status);
  const currentIndex = cells.indexOf("current");
  const reworkIndex = cells.indexOf("rework");
  const spoken =
    currentIndex >= 0
      ? `진행 단계 ${SITE_PROGRESS_STAGES.length}단계 중 ${currentIndex + 1}단계 · ${SITE_PROGRESS_STAGES[currentIndex].label}`
      : reworkIndex >= 0
        ? `${SITE_PROGRESS_STAGES[reworkIndex].label} 단계로 되돌아감 · ${note}`
        : `진행 단계 표시 없음 · ${note}`;

  return (
    <span className="flex flex-col gap-1">
      <span className="flex gap-0.5" role="img" aria-label={spoken}>
        {cells.map((cell, index) => (
          <span
            key={SITE_PROGRESS_STAGES[index].status}
            className={`h-[5px] w-[9px] rounded-[1px] ${CELL_CLASS[cell]}`}
          />
        ))}
      </span>
      {note && <span className="text-[10.5px] break-keep text-ink-muted">{note}</span>}
    </span>
  );
}
