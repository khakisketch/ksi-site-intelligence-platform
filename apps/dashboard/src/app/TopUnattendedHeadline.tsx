"use client";

import { formatElapsed } from "@/lib/core-api/triage";
import { useTick } from "@/hooks/useTick";

/**
 * 홈 콜아웃의 "N분째 미조치 이벤트가 있습니다" 헤드라인 — page.tsx 가 서버 렌더
 * 시점에 고정해 보여주던 문장을 마운트 후 60초마다 실제 경과로 갈아탄다.
 *
 * 텍스트·조건은 page.tsx 의 원래 서버 계산과 완전히 동일한 로직을 그대로
 * 재사용한다(formatElapsed + "방금 들어옴" 특수 문구 분기) — 판정을 새로 만들지 않는다.
 *
 * `initialText` 는 page.tsx 가 서버 렌더 시점에 같은 로직으로 미리 계산해 넘긴 값 —
 * 마운트 전(SSR·최초 페인트)엔 이 값을 그대로 보여준다. `formatElapsed` 는 로케일
 * 포매터를 쓰지 않는 순수 문자열 조합이라(ElapsedTime.tsx 의 절대시각 표기와 달리)
 * 첫 렌더에서 서버·클라이언트가 갈릴 이유가 없어 suppressHydrationWarning 이 필요 없다.
 */
export function TopUnattendedHeadline({
  occurredAt,
  initialText,
}: {
  occurredAt: string;
  initialText: string;
}) {
  const now = useTick(60_000);
  if (now === null) return <>{initialText}</>;

  const elapsedLabel = formatElapsed(now - new Date(occurredAt).getTime(), { unattended: true });
  return (
    <>{elapsedLabel === "방금 들어옴" ? "방금 들어온 확인 항목이 있습니다" : `${elapsedLabel} 확인되지 않은 항목이 있습니다`}</>
  );
}
