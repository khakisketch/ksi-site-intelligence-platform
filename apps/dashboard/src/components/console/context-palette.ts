import type { PaletteItem } from "./palette-items";

/** 이미 인가된 현장 항목에서만 현재 현장의 읽기 목적지를 만든다. */
export function contextPaletteItems(items: readonly PaletteItem[], pathname: string): PaletteItem[] {
  const site = items.find((item) => item.group === "현장" && (pathname === item.href || pathname.startsWith(`${item.href}/`)));
  if (!site) return [];
  return [
    { key: `${site.key}:analysis`, label: "분석·검토", group: "현재 현장", hint: site.label, href: `${site.href}/analysis`, keywords: "비교 기준 결과 근거 검토" },
    { key: `${site.key}:data`, label: "자료", group: "현재 현장", hint: site.label, href: `${site.href}/spatial-assets`, keywords: "촬영 사진 정사영상 높이 DSM 파일" },
    { key: `${site.key}:prepare`, label: "구역 자료 준비", group: "현재 현장", hint: site.label, href: `${site.href}/spatial-data-requests`, keywords: "내보내기 받기 다운로드 요청" },
  ];
}
