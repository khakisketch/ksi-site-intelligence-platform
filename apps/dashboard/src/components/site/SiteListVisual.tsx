import { DefaultSiteVisual } from "./DefaultSiteVisual";

/**
 * 목록용 기본 표시 — Home 캐러셀과 같은 중립 장식이다.
 *
 * 현장별 실제 관측 이미지를 보여주는 계약·해상도가 목록에 없으므로(ADR025 D6),
 * 지도·사진처럼 보이는 것은 일절 쓰지 않는다. 완만한 등고선 장식
 * (DefaultSiteVisual: 축·격자·폴리곤·측정점 없음)에 씨앗=siteId 를 넣어
 * 같은 현장은 늘 같은 모양으로 보인다.
 *
 * 바깥 문구가 뜻을 말하므로 전체를 장식(aria-hidden)으로 둔다 — 목록에서
 * 행마다 "기본 이미지"를 읽으면 소음이다. 보이는 작은 표식은 보는 사람에게
 * 이것이 실제 현장 모습이 아님을 밝힌다.
 */
export function SiteListVisual({
  siteId,
  className = "h-12 w-16",
}: {
  siteId: string;
  className?: string;
}) {
  return (
    <div
      aria-hidden="true"
      className={`relative shrink-0 overflow-hidden rounded-md border border-line bg-sunk ${className}`}
    >
      <DefaultSiteVisual seed={siteId} className="absolute inset-0 size-full" />
      <span className="absolute bottom-1 left-1 rounded bg-surface/90 px-1 py-px text-[10px] leading-4 font-semibold text-ink-2">
        기본 이미지
      </span>
    </div>
  );
}
