import { notFound } from "next/navigation";

import { NAV_ITEMS } from "@/components/nav/nav-items";
import { EmptyState } from "@/components/ui/EmptyState";

// 기존 deep link는 보존하되, ADR-KSI-039의 제품 책임 밖 기능을 출시 대기로 표현하지 않는다.
// 이 경로로 남은 항목은 메뉴의 fleet 하나뿐이다. 메뉴에 없는 section은 notFound로 끝난다.
const SCOPE_NOTICE: Record<string, { title: string; description: string; action: { label: string; href: string } }> = {
  fleet: {
    title: "장비 운용은 제품 범위 밖입니다",
    description: "비행·장비 제어·취득·고객 운영 재구성은 KSI Site Intelligence의 제품 범위 밖입니다. 이 경로는 기존 링크를 위한 범위 안내이며, 장비 운영 화면이나 향후 지원 약속이 아닙니다.",
    action: { label: "계정·도움말", href: "/more" },
  },
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
  const notice = Object.hasOwn(SCOPE_NOTICE, section) ? SCOPE_NOTICE[section] : undefined;
  if (!item || !notice) notFound();

  return (
    <div className="p-4 sm:p-5">
      <EmptyState title={notice.title} description={notice.description} action={notice.action} />
    </div>
  );
}
