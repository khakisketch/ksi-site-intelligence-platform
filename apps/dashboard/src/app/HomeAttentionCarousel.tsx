"use client";

import Link from "next/link";

import { useEffect, useRef, useState } from "react";

export interface HomeAttentionCardView {
  key: string;
  siteName: string;
  label: string;
  title: string;
  detail: string;
  /** 표시 시점의 실제 의미(분석 생성·작업 갱신·현장 갱신·결과 보고).
   *  원장 필드마다 뜻이 달라 라벨 없이 시각만 두면 다른 시점으로 오독된다 —
   *  page.tsx가 구조화된 출처 분기로 정하고 문자열 추론은 하지 않는다. */
  timeLabel: string;
  observedAt: string;
  href: string;
  actionLabel: string;
  /**
   * 승인된 실제 등록 근거 이미지(만료 제한 presigned URL)만 담는다. 합성·고정
   * placeholder·다른 현장 사진은 절대 넣지 않는다(ADR-KSI-025 D3). 조회하지
   * 않은 미리보기의 부재는 이미지 없음이 아니라 null 로 둔다 — null 은 빈 칸이
   * 아니라 텍스트 브리핑이며, 등록 자료의 부재를 뜻하지 않는다.
   */
  image: { src: string; alt: string } | null;
  /** 접어 두는 기술 참조(분석·구역 ID 등). 있을 때만 키보드로 펼칠 수 있게 둔다. */
  technicalRef?: string;
}

function ArrowIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
      {direction === "left" ? <path d="m15 18-6-6 6-6" /> : <path d="m9 6 6 6-6 6" />}
    </svg>
  );
}

/**
 * 확인할 현장 브리핑 — 내용 우선, 고정 큰 시각 없음(ADR-KSI-025 D7).
 *
 * 이미지 prop 이 null 이면 장식 표지·빈 사진 칸을 두지 않고 현장명·안건·근거
 * 시점·행동을 텍스트로 읽힌다. 실제 연결된 허용 이미지가 있을 때만 경계가
 * 있는 작은 figure 로 함께 보여주며, 그때도 카드 높이는 내용이 정한다.
 * 1024px 미만에서는 한 장씩 수동으로 넘기는 snap 캐러셀(D2: 이전·다음 버튼,
 * 현재 위치 점, 키보드, reduced-motion, 자동 넘김 없음)이고, 데스크톱에서는
 * 여러 안건을 한 번에 이해하도록 순서대로 전부 펼친다.
 */
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
          <h2 id="home-attention-heading" className="text-[22px] leading-tight font-bold tracking-[-0.03em] break-keep sm:text-[26px]">
            {title}
          </h2>
          {description && <p className="mt-1 max-w-3xl text-[12.5px] leading-5 break-keep text-ink-2">{description}</p>}
        </div>
        {items.length > 1 && (
          <div className="flex shrink-0 gap-2 lg:hidden">
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
        className="home-carousel-track flex snap-x snap-mandatory gap-3 overflow-x-auto lg:grid lg:grid-cols-1 lg:overflow-visible"
      >
        {items.map((item) => (
          <article
            key={item.key}
            className="min-w-full snap-start overflow-hidden rounded-lg border border-line bg-surface lg:min-w-0"
          >
            {item.image && (
              <figure className="border-b border-line bg-sunk">
                {/* Presigned evidence URLs are short-lived and cannot use the static next/image host allowlist. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={item.image.src}
                  alt={item.image.alt}
                  loading="lazy"
                  referrerPolicy="no-referrer"
                  className="max-h-56 w-full object-cover"
                />
                <figcaption className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-4 py-2">
                  <span className="text-[12px] font-semibold break-keep">{item.siteName}</span>
                  <span className="num text-[10.5px] text-ink-2">{item.timeLabel} {item.observedAt}</span>
                </figcaption>
              </figure>
            )}

            <div className="flex min-w-0 flex-col gap-2 p-4 sm:p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <p className="min-w-0 text-[13px] font-bold break-keep">{item.siteName}</p>
                <p className="num shrink-0 text-[11px] text-ink-muted">{item.timeLabel} {item.observedAt}</p>
              </div>
              <p className="text-[11.5px] font-bold tracking-[0.03em] text-accent">{item.label}</p>
              <h3 className="text-[19px] leading-snug font-bold tracking-[-0.025em] break-keep sm:text-[22px]">
                {item.title}
              </h3>
              <p className="text-[13px] leading-6 break-keep text-ink-2">{item.detail}</p>
              {item.technicalRef && (
                <details className="text-[11.5px] text-ink-muted">
                  <summary className="tap-target inline-flex cursor-pointer items-center font-semibold">
                    기술 참조 정보
                  </summary>
                  <p className="mt-1 break-all">{item.technicalRef}</p>
                </details>
              )}
              <Link href={item.href} className="btn btn-primary mt-2 w-full justify-between sm:w-fit sm:min-w-44">
                {item.actionLabel}
                <ArrowIcon direction="right" />
              </Link>
            </div>
          </article>
        ))}
      </div>

      {items.length > 1 && (
        <div className="flex min-h-9 items-center justify-between gap-4 lg:hidden" aria-live="polite">
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
