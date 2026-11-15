import Link from "next/link";

/**
 * 분석 섹션의 컨텍스트 패널 — 어떤 분석을 볼지 고른다(ADR-KSI-043의 2단).
 * 지금 고를 수 있는 보기만 둔다: 변화 분석(두 시점 비교)과 외부 비교. 준비되지 않은 분석 유형은 표시하지 않는다.
 * 넓은 화면은 왼쪽 열에 세로로, 좁은 화면은 본문 위에 가로로 놓인다.
 */
export function AnalysisContextPanel({ siteId, active, spaceHref = null }: { siteId: string; active: "change" | "external"; spaceHref?: string | null }) {
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const views = [
    { key: "change", label: "변화 분석", href: `${sitePath}/analysis` },
    { key: "external", label: "외부 비교", href: `${sitePath}/observations` },
  ] as const;
  return (
    <div className="flex min-w-0 flex-col gap-4">
    <nav aria-label="분석 보기" className="flex min-w-0 flex-col gap-1.5">
      <h2 className="px-1 text-micro font-bold tracking-wide text-ink-muted">분석 종류</h2>
      <ul className="flex flex-wrap gap-1 xl:flex-col xl:gap-0.5">
        {views.map(({ key, label, href }) => (
          <li key={key}>
            <Link
              href={href}
              aria-current={active === key ? "page" : undefined}
              className={`tap-target flex min-w-0 items-center rounded-md border px-2.5 text-body break-words hover:bg-sunk xl:border-transparent ${active === key ? "border-line-strong bg-sunk font-semibold" : "border-line text-ink-2"}`}
            >
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
    {spaceHref && (
      // 탐색하던 구역·자료 맥락을 그대로 들고 공간으로 돌아간다.
      <Link href={spaceHref} className="tap-target flex items-center rounded-md border border-line px-2.5 text-body text-ink-2 hover:bg-sunk">공간으로 돌아가기</Link>
    )}
    </div>
  );
}
