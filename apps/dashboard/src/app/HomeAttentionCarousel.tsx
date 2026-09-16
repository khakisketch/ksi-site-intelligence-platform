"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

export interface HomeAttentionCardView {
  key: string;
  siteName: string;
  label: string;
  title: string;
  detail: string;
  observedAt: string;
  href: string;
  actionLabel: string;
  image: { src: string; alt: string } | null;
  imageFallback: { label: string; detail: string };
}

function ArrowIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
      {direction === "left" ? <path d="m15 18-6-6 6-6" /> : <path d="m9 6 6 6-6 6" />}
    </svg>
  );
}

export function HomeAttentionCarousel({
  items,
  title = "확인이 필요한 현장",
  description,
  regionLabel = "확인 필요 현장 캐러셀",
}: {
  items: HomeAttentionCardView[];
  title?: string;
  description?: string;
  regionLabel?: string;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    function realignAfterResize() {
      const track = trackRef.current;
      if (!track) return;
      track.scrollTo({ left: activeIndex * track.clientWidth, behavior: "auto" });
    }
    window.addEventListener("resize", realignAfterResize);
    return () => window.removeEventListener("resize", realignAfterResize);
  }, [activeIndex]);

  function moveTo(nextIndex: number) {
    const bounded = Math.max(0, Math.min(items.length - 1, nextIndex));
    const track = trackRef.current;
    if (!track) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    track.scrollTo({
      left: bounded * track.clientWidth,
      behavior: reduceMotion ? "auto" : "smooth",
    });
    setActiveIndex(bounded);
  }

  function updateActiveIndex() {
    const track = trackRef.current;
    if (!track || track.clientWidth === 0) return;
    setActiveIndex(Math.max(0, Math.min(items.length - 1, Math.round(track.scrollLeft / track.clientWidth))));
  }

  return (
    <section aria-labelledby="home-attention-heading" className="flex min-w-0 flex-col gap-3">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-[11.5px] font-semibold tracking-[0.04em] text-accent uppercase">현장 인텔리전스</p>
          <h2 id="home-attention-heading" className="mt-1 text-[22px] leading-tight font-bold tracking-[-0.03em] break-keep sm:text-[26px]">
            {title}
          </h2>
          {description && <p className="mt-1 max-w-3xl text-[12.5px] leading-5 break-keep text-ink-2">{description}</p>}
        </div>
        {items.length > 1 && (
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              aria-label="이전 현장"
              disabled={activeIndex === 0}
              onClick={() => moveTo(activeIndex - 1)}
              className="tap-target inline-grid size-10 place-items-center rounded-md border border-line-strong bg-surface text-ink-1 transition-colors hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-35"
            >
              <ArrowIcon direction="left" />
            </button>
            <button
              type="button"
              aria-label="다음 현장"
              disabled={activeIndex === items.length - 1}
              onClick={() => moveTo(activeIndex + 1)}
              className="tap-target inline-grid size-10 place-items-center rounded-md border border-line-strong bg-surface text-ink-1 transition-colors hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-35"
            >
              <ArrowIcon direction="right" />
            </button>
          </div>
        )}
      </div>

      <div
        ref={trackRef}
        role="region"
        aria-label={regionLabel}
        onScroll={updateActiveIndex}
        className="home-carousel-track flex snap-x snap-mandatory overflow-x-auto"
      >
        {items.map((item, index) => (
          <article
            key={item.key}
            className="grid min-w-full snap-start overflow-hidden rounded-lg border border-line bg-surface lg:grid-cols-[minmax(0,1.25fr)_minmax(300px,0.75fr)]"
          >
            {item.image ? (
              <div className="relative min-h-[208px] overflow-hidden bg-sunk sm:min-h-[270px] lg:min-h-[330px]">
                {/* Presigned evidence URLs are short-lived and cannot use the static next/image host allowlist. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={item.image.src}
                  alt={item.image.alt}
                  loading={index === 0 ? "eager" : "lazy"}
                  referrerPolicy="no-referrer"
                  className="absolute inset-0 size-full object-cover"
                />
                <div className="absolute right-0 bottom-0 left-0 flex items-end justify-between gap-3 bg-linear-to-t from-black/75 to-transparent px-4 pt-12 pb-3 text-white">
                  <span className="text-[12px] font-semibold break-keep">{item.siteName}</span>
                  <span className="num shrink-0 text-[10.5px]">{item.observedAt}</span>
                </div>
              </div>
            ) : (
              <div className="relative min-h-[208px] overflow-hidden bg-sunk sm:min-h-[270px] lg:min-h-[330px]">
                <svg
                  aria-hidden="true"
                  viewBox="0 0 640 360"
                  preserveAspectRatio="xMidYMid slice"
                  className="absolute inset-0 size-full"
                >
                  <rect width="640" height="360" fill="var(--sunk)" />
                  <path d="M0 72h640M0 144h640M0 216h640M0 288h640M128 0v360M256 0v360M384 0v360M512 0v360" stroke="var(--line)" />
                  <path d="m70 272 82-116 112 33 68-102 110 41 126-70" fill="none" stroke="var(--line-strong)" strokeWidth="2" />
                  <path d="m105 276 82-78 86 25 61-73 102 35 89-51 42 79-104 74-126-20-94 38Z" fill="var(--surface)" fillOpacity="0.66" stroke="var(--line-strong)" strokeDasharray="8 8" />
                  <circle cx="337" cy="221" r="8" fill="var(--accent)" />
                </svg>

                {/* 코너 배지 — 불가 안내가 근거 영역 전체를 덮는 큰 흰 박스가 되지
                    않는다(B7). 아래 배경 SVG가 계속 보인다. */}
                <div className="absolute top-3 left-3 max-w-[calc(100%-24px)] rounded-lg border border-line-strong bg-surface/95 px-3 py-2 shadow-sm backdrop-blur-sm">
                  <span className="text-[11px] font-bold text-ink-1">{item.imageFallback.label}</span>
                  <p className="mt-0.5 text-[11.5px] leading-5 break-keep text-ink-2">{item.imageFallback.detail}</p>
                </div>

                <div className="absolute right-0 bottom-0 left-0 flex items-end justify-between gap-3 bg-linear-to-t from-black/65 to-transparent px-4 pt-12 pb-3 text-white">
                  <span className="text-[12px] font-semibold break-keep">{item.siteName}</span>
                  <span className="num shrink-0 text-[10.5px]">{item.observedAt}</span>
                </div>
              </div>
            )}

            <div className="flex min-w-0 flex-col justify-between gap-5 p-4 sm:p-5 lg:p-6">
              <div>
                <p className="text-[11.5px] font-bold tracking-[0.03em] text-accent">{item.label}</p>
                <h3 className="mt-2 text-[19px] leading-snug font-bold tracking-[-0.025em] break-keep sm:text-[22px]">
                  {item.title}
                </h3>
                <p className="mt-3 text-[13px] leading-6 break-keep text-ink-2">{item.detail}</p>
              </div>
              <Link href={item.href} className="btn btn-primary w-full justify-between sm:w-fit sm:min-w-44">
                {item.actionLabel}
                <ArrowIcon direction="right" />
              </Link>
            </div>
          </article>
        ))}
      </div>

      {items.length > 1 && (
        <div className="flex min-h-9 items-center justify-between gap-4" aria-live="polite">
          <div className="flex items-center gap-2" aria-label={`${items.length}개 현장 중 ${activeIndex + 1}번째`}>
            {items.map((item, index) => (
              <button
                key={item.key}
                type="button"
                aria-label={`${index + 1}번째 현장: ${item.siteName}`}
                aria-current={index === activeIndex ? "true" : undefined}
                onClick={() => moveTo(index)}
                className="tap-target group inline-grid min-h-9 min-w-9 place-items-center"
              >
                <span className={`h-1.5 rounded-full transition-all ${index === activeIndex ? "w-6 bg-accent" : "w-1.5 bg-line-strong group-hover:bg-ink-muted"}`} />
              </button>
            ))}
          </div>
          {/* 점 페이지네이션과 같은 정보(현재 위치)를 다시 숫자로 말하지 않는다(B7)
              — 여기는 현재 카드의 현장명만 보조로 보여준다. */}
          <p className="min-w-0 truncate text-right text-[11.5px] font-semibold text-ink-2">
            {items[activeIndex]?.siteName}
          </p>
        </div>
      )}
    </section>
  );
}
