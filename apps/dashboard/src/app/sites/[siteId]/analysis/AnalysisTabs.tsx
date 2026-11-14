import Link from "next/link";

export function AnalysisTabs({
  siteId,
  active,
}: {
  siteId: string;
  active: "change" | "external";
}) {
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const views = [
    { key: "change", label: "변화 분석", href: `${sitePath}/analysis` },
    { key: "external", label: "외부 비교", href: `${sitePath}/observations` },
  ] as const;

  return (
    <nav aria-label="분석 보기" className="flex gap-2 border-b border-line">
      {views.map(({ key, label, href }) => (
        <Link key={key} href={href} aria-current={active === key ? "page" : undefined}
          className={`tap-target inline-flex min-h-11 items-center border-b-2 px-3 text-body ${
            active === key ? "border-ink-1 font-bold text-ink-1" : "border-transparent text-ink-2 hover:border-line-strong hover:text-ink-1"
          }`}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
