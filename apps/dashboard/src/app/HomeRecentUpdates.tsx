import Link from "next/link";

export interface HomeRecentUpdateView {
  key: string;
  siteName: string;
  label: string;
  title: string;
  detail: string;
  observedAt: string;
  href: string;
  image: { src: string; alt: string } | null;
  imageFallbackLabel: string;
}

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

export function HomeRecentUpdates({ items }: { items: HomeRecentUpdateView[] }) {
  // 경영 홈은 확인할 결과가 있을 때만 이 영역을 만든다. 빈 섹션을 채우기 위한
  // 설명은 사용자가 해야 할 판단을 늘리지 않고 홈의 정보 밀도만 떨어뜨린다.
  if (items.length === 0) return null;

  return (
    <section aria-labelledby="home-recent-updates" className="flex flex-col gap-3 border-t border-line pt-5 sm:pt-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 id="home-recent-updates" className="text-[17px] font-bold tracking-[-0.02em]">최근 업데이트</h2>
          <p className="mt-1 text-[12px] break-keep text-ink-2">결과와 사람이 정리한 안건만 표시합니다.</p>
        </div>
        <Link href="/sites" className="tap-target inline-flex items-center text-[12px] font-semibold text-accent hover:underline">
          현장 전체
        </Link>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              aria-label={`${item.siteName}, ${item.label}, ${item.title}`}
              className="group grid min-w-0 overflow-hidden rounded-lg border border-line bg-surface transition-colors hover:border-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {item.image && (
                <div className="relative min-h-[132px] overflow-hidden bg-sunk sm:min-h-[158px]">
                  {/* Presigned evidence URLs are short-lived and bypass static image optimization. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={item.image.src}
                    alt={item.image.alt}
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    className="absolute inset-0 size-full object-cover transition-transform duration-200 motion-reduce:transition-none group-hover:scale-[1.015]"
                  />
                  <span className="absolute right-3 bottom-3 rounded-full bg-black/70 px-2 py-1 text-[10.5px] font-medium text-white">
                    {item.observedAt}
                  </span>
                </div>
              )}
              <div className="flex min-w-0 flex-col p-4">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <p className="text-[11px] font-bold tracking-[0.02em] text-accent">{item.label} · {item.siteName}</p>
                  {!item.image && (
                    <span className="rounded-full border border-line px-2 py-0.5 text-[10.5px] font-medium text-ink-muted">
                      {item.imageFallbackLabel}
                    </span>
                  )}
                  {!item.image && <span className="num ml-auto text-[10.5px] text-ink-muted">{item.observedAt}</span>}
                </div>
                <h3 className="mt-2 text-[15px] leading-snug font-bold tracking-[-0.015em] break-keep">{item.title}</h3>
                <p className="mt-2 text-[12px] leading-5 break-keep text-ink-2">{item.detail}</p>
                <span className="mt-3 inline-flex min-h-9 items-center justify-between text-[12px] font-semibold text-ink-1">
                  내용 보기 <ArrowIcon />
                </span>
              </div>
            </Link>
        ))}
      </div>
    </section>
  );
}
