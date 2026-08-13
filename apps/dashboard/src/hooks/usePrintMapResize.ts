"use client";

import { useEffect } from "react";
import type { Map as LeafletMap } from "leaflet";

/**
 * 인쇄 프리뷰로 들고 날 때 Leaflet 지도 크기를 다시 맞춘다(M4-D 현장 보고서).
 *
 * Leaflet 은 마운트 시점의 컨테이너 픽셀 크기를 캐싱한다(`map._size`) — `@media
 * print` 가 레이아웃을 바꿔도(예: 화면 전용 `h-screen`/`overflow-hidden` 리셋으로
 * 컨테이너 높이가 달라짐) 지도는 그 사실을 모른다. `invalidateSize()` 를 강제로
 * 부르지 않으면 인쇄 결과에서 지도가 잘리거나 타일 일부가 빈 채로 남는다.
 *
 * `matchMedia('print')` 의 `change` 만으로는 부족하다 — 크롬은 인쇄 프리뷰 진입과
 * 거의 같이 쏘지만 일부 브라우저는 `beforeprint`/`afterprint` 에서만 확실히
 * 신호를 준다. 그래서 셋을 모두 듣는다.
 */
export function usePrintMapResize(map: LeafletMap): void {
  useEffect(() => {
    const invalidate = () => map.invalidateSize();
    const mediaQuery = window.matchMedia("print");
    // 구형 Safari 는 MediaQueryList.addEventListener 가 없다 — addListener 폴백.
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener("change", invalidate);
    } else {
      mediaQuery.addListener(invalidate);
    }
    window.addEventListener("beforeprint", invalidate);
    window.addEventListener("afterprint", invalidate);
    return () => {
      if (mediaQuery.removeEventListener) {
        mediaQuery.removeEventListener("change", invalidate);
      } else {
        mediaQuery.removeListener(invalidate);
      }
      window.removeEventListener("beforeprint", invalidate);
      window.removeEventListener("afterprint", invalidate);
    };
  }, [map]);
}
