import { Disclosure } from "@/components/ui/Disclosure";
import Link from "next/link";

import { SiteVisualPlaceholder } from "@/components/site/SiteVisualPlaceholder";

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

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}

/**
 * 확인할 현장 브리핑 — 세로 목록(ADR-KSI-025 D8).
 *
 * 한 행은 현장 표식 · (현장명·안건 종류·근거 시점) · 제목 · 세부 · 다음 행동이다.
 * 가로로 넘기는 캐러셀은 두지 않는다 — 안건이 몇 개인지 한눈에 보이고, 모바일에서도
 * 넘기기 없이 위에서 아래로 읽는다. 순서는 호출자가 정한 우선순위 그대로다.
 *
 * 이미지 prop 이 null 이면 장식 표지·빈 사진 칸을 두지 않는다. 실제 연결된 허용
 * 이미지가 있을 때만 작은 썸네일(figure)을 앞에 둔다. 두 경우 모두 행 높이는
 * 내용이 정한다.
 */
export function HomeAttentionList({
  items,
  title = "확인이 필요한 현장",
  description,
  regionLabel = "확인 필요 현장 목록",
}: {
  items: HomeAttentionCardView[];
  title?: string;
  description?: string;
  regionLabel?: string;
}) {
  return (
    <section aria-labelledby="home-attention-heading" className="flex min-w-0 flex-col gap-3">
      <div>
        <h2 id="home-attention-heading" className="text-title font-bold tracking-[-0.02em] break-keep sm:text-display">
          {title}
        </h2>
        {description && <p className="mt-1 max-w-3xl text-caption break-keep text-ink-2">{description}</p>}
      </div>

      <div role="region" aria-label={regionLabel}>
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
          {items.map((item) => (
            <li key={item.key}>
              <article className="flex min-w-0 flex-col gap-x-4 gap-y-3 px-4 py-3 sm:flex-row sm:items-center">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  {item.image ? (
                    <figure className="w-24 flex-none overflow-hidden rounded-md border border-line bg-sunk">
                      {/* Presigned evidence URLs are short-lived and cannot use the static next/image host allowlist. */}
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
                    <SiteVisualPlaceholder siteName={item.siteName} label={item.label} size="mini" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-caption text-ink-2">
                      <span className="font-semibold break-keep text-ink-1">{item.siteName}</span>
                      <span aria-hidden="true" className="text-ink-muted">·</span>
                      <span className="break-keep">{item.label}</span>
                      <span className="num ml-auto text-micro text-ink-muted">{item.timeLabel} {item.observedAt}</span>
                    </p>
                    <h3 className="mt-0.5 text-lead font-semibold break-keep">{item.title}</h3>
                    <p className="mt-0.5 max-w-[72ch] text-caption break-keep text-ink-2">{item.detail}</p>
                    {item.technicalRef && (
                      <Disclosure label="식별 상세" className="text-micro text-ink-muted">
                        <p className="mt-1 break-all">{item.technicalRef}</p>
                      </Disclosure>
                    )}
                  </div>
                </div>
                <Link href={item.href} className="btn btn-sm w-full shrink-0 justify-between sm:w-auto sm:min-w-40">
                  {item.actionLabel}
                  <ArrowIcon />
                </Link>
              </article>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
