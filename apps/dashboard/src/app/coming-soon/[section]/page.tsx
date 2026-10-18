import { notFound } from "next/navigation";

import { NAV_ITEMS } from "@/components/nav/nav-items";
import { EmptyState } from "@/components/ui/EmptyState";

// 기존 deep link는 보존하되, ADR-KSI-039의 제품 책임 밖 기능을 출시 대기로 표현하지 않는다.
const SECTION_BLURB: Record<string, string> = {
  fleet: "비행·장비 제어·취득·고객 운영 재구성은 KSI Site Intelligence의 제품 범위 밖입니다. 이 경로는 기존 링크를 위한 범위 안내이며, 장비 운영 화면이나 향후 지원 약속이 아닙니다.",
  data: "수집 데이터와 AI 모델을 관리하는 화면입니다.",
};

const AVAILABLE_NEXT_ACTION: Record<string, { label: string; href: string }> = {
  fleet: { label: "더보기", href: "/more" },
  data: { label: "현장 상태 보기", href: "/sites" },
};

// TopBar 가 이미 섹션 이름 h1(item.label) 을 렌더한다(page-title.ts) — 본문에서
// 같은 이름을 또 찍지 않고, EmptyState 의 title 은 일반화된 문구로 둔다.
export default async function ComingSoonPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  const item = NAV_ITEMS.find((i) => i.href === `/coming-soon/${section}`);
  if (!item) notFound();
  const nextAction = AVAILABLE_NEXT_ACTION[section] ?? { label: "홈으로", href: "/" };

  return (
    <div className="p-4 sm:p-5">
      <EmptyState
        title={section === "fleet" ? "장비 운용은 제품 범위 밖입니다" : "준비 중인 기능입니다"}
        description={section === "fleet" ? SECTION_BLURB.fleet : `${SECTION_BLURB[section] ?? `${item.label} 화면은 아직 준비 중입니다.`} 현재 이 기능의 운영 데이터와 제어 API는 대시보드에 연결되지 않았습니다.`}
        action={nextAction}
      />
    </div>
  );
}
