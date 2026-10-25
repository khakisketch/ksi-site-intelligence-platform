import Link from "next/link";

/**
 * 업무 안의 세 갈래(관측 작업·받은 업무·작업 팀) 전환 — 한 번에 한 화면만 연다.
 *
 * - 관측 작업(/field)은 조직의 관측 작업 기록 목록이다. 개인 할당 목록이 아니다.
 * - 받은 업무(/field/inbox)는 나에게 배정·공유된 항목만 둔다. 읽음 상태는
 *   서버가 정하고, 목록을 여는 것만으로 바꾸지 않는다.
 * - 팀 관리(/field/team)는 배정·공유에 쓰는 팀원 정보다. 조직 관리 화면이 아니다.
 *   볼 수 있는 계정에만 탭을 둔다(호출자가 정한다).
 */
export function FieldWorkNav({
  active,
  showTeam,
}: {
  active: "orders" | "inbox" | "team";
  showTeam: boolean;
}) {
  const tabs = [
    { key: "inbox", label: "받은 업무", href: "/field/inbox" },
    { key: "orders", label: "전체 관측 작업", href: "/field" },
    ...(showTeam ? [{ key: "team", label: "팀 관리", href: "/field/team" }] : []),
  ] as const;
  return (
    <nav aria-label="업무 보기 방식" className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((option) => {
        const current = option.key === active;
        return (
          <Link
            key={option.key}
            href={option.href}
            aria-current={current ? "page" : undefined}
            className={`tap-target relative inline-flex min-h-11 shrink-0 items-center border-b-2 px-3 text-[13px] whitespace-nowrap transition-colors ${
              current
                ? "border-ink-1 font-bold text-ink-1"
                : "border-transparent text-ink-2 hover:border-line-strong hover:text-ink-1"
            }`}
          >
            {option.label}
          </Link>
        );
      })}
    </nav>
  );
}
