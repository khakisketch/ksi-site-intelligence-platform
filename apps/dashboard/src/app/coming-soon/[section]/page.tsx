import { notFound } from "next/navigation";

import { NAV_ITEMS } from "@/components/nav/nav-items";
import { EmptyState } from "@/components/ui/EmptyState";

// PRD §7.1 taxonomy 자리는 유지하되 S3 비범위 항목은 정직하게 "준비 중"이라 밝힌다
// (UX 목표 §6 — 링크를 숨기지 않는다, INV-040 과 같은 정신).
//
// 섹션별 한 줄 설명은 PRD §7.1 데스크톱 사이드 메뉴 taxonomy 의 항목명 자체가 뜻하는
// 범위를 그대로 풀어 쓴 것이다 — 수치·일정·건수 등 API 가 안 주는 값은 넣지 않는다.
//
// 2026-08-17: 준비 중으로 남은 fleet·data 만 둔다. assets·world·reports·settings 는
// 2026-08-08 에 실동작으로 전환돼 아래 notFound() 가드에 걸리므로 **도달 불가능한 죽은
// 문자열**이었는데, 그중 settings 항목("계정·조직 설정을 관리하는 화면입니다")이 화면에
// 보인 적도 없으면서 코드를 읽는 다음 구현자에게 그 슬롯의 정의로 읽혔다. 실제 /settings
// 는 장비 지원단계 표 하나다 — 그래서 라벨도 "장비 지원단계"로 고쳤다(nav-items.ts).
const SECTION_BLURB: Record<string, string> = {
  fleet: "기체·Edge 장비 상태를 관리하는 화면입니다.",
  data: "수집 데이터와 AI 모델을 관리하는 화면입니다.",
};

const AVAILABLE_NEXT_ACTION: Record<string, { label: string; href: string }> = {
  fleet: { label: "장비 지원 단계 보기", href: "/settings" },
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
        title="준비 중인 기능입니다"
        description={`${SECTION_BLURB[section] ?? `${item.label} 화면은 아직 준비 중입니다.`} 현재 이 기능의 운영 데이터와 제어 API는 대시보드에 연결되지 않았습니다.`}
        action={nextAction}
      />
    </div>
  );
}
