import Link from "next/link";

import { SiteVisualPlaceholder } from "@/components/site/SiteVisualPlaceholder";

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

  // 확인 목록과 같은 한 행 구조다 — 큰 카드·띠 대신 현장 표식, 현장명·종류·시점,
  // 제목, 세부를 한 줄 묶음으로 읽고 행 전체가 링크다. 실제 근거 이미지가 있을
  // 때만 작은 썸네일이 표식을 대신한다(D3: 합성·고정 placeholder 금지).
  return (
    <section aria-labelledby="home-recent-updates" className="flex flex-col gap-3 border-t border-line pt-5 sm:pt-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 id="home-recent-updates" className="text-title font-bold tracking-[-0.02em]">최근 업데이트</h2>
          <p className="mt-1 text-caption break-keep text-ink-2">결과와 사람이 정리한 안건만 표시합니다.</p>
        </div>
        <Link href="/sites" className="tap-target inline-flex items-center text-caption font-semibold text-accent-text hover:underline">
          현장 전체
        </Link>
      </div>

      <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
        {items.map((item) => (
          <li key={item.key}>
            <Link
              href={item.href}
              aria-label={`${item.siteName}, ${item.label}, ${item.title}`}
              className="group flex min-w-0 items-center gap-3 px-4 py-3 transition-colors hover:bg-page focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
            >
              {item.image ? (
                <figure className="w-20 flex-none overflow-hidden rounded-md border border-line bg-sunk">
                  {/* Presigned evidence URLs are short-lived and bypass static image optimization. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={item.image.src}
                    alt={item.image.alt}
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    className="block aspect-[3/2] w-full object-cover"
                  />
                </figure>
              ) : (
                <SiteVisualPlaceholder siteName={item.siteName} label={item.imageFallbackLabel} size="mini" />
              )}
              <div className="min-w-0 flex-1">
                <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-caption text-ink-2">
                  <span className="font-semibold break-keep text-ink-1">{item.siteName}</span>
                  <span aria-hidden="true" className="text-ink-muted">·</span>
                  <span className="break-keep">{item.label}</span>
                  <span className="num ml-auto text-micro text-ink-muted">{item.observedAt}</span>
                </p>
                <h3 className="mt-0.5 text-lead font-semibold break-keep">{item.title}</h3>
                <p className="mt-0.5 max-w-[72ch] text-caption break-keep text-ink-2">{item.detail}</p>
              </div>
              <span className="flex-none text-ink-muted group-hover:text-ink-1"><ArrowIcon /></span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
