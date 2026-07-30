import { notFound } from "next/navigation";

import { NAV_ITEMS } from "@/components/nav/nav-items";

// PRD §7.1 taxonomy 자리는 유지하되 S3 비범위 항목은 정직하게 "준비 중"이라 밝힌다
// (UX 목표 §6 — 링크를 숨기지 않는다, INV-040 과 같은 정신).
export default async function ComingSoonPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  const item = NAV_ITEMS.find((i) => i.href === `/coming-soon/${section}`);
  if (!item) notFound();

  return (
    <div className="flex flex-col items-center gap-2 p-10 text-center">
      <h1 className="text-lg font-medium break-keep">{item.label}</h1>
      <p className="text-foreground/60 break-keep">이 화면은 아직 준비 중입니다.</p>
    </div>
  );
}
