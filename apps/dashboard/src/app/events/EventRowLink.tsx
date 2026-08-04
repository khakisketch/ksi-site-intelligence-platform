"use client";

// 마스터-디테일 전환의 유일한 클라이언트 조각 — 서버는 뷰포트를 모르므로 lg(1024)
// 분기는 여기서만 판단할 수 있다(시안 triage-d-ink-mono.html 주석: 1024를 1급
// 레이아웃으로 둔다).
//
//   lg 미만 / JS 없음 / 새 탭(가운데클릭·수정키)  → href 그대로: 상세 페이지 이동(기존 동작 유지)
//   lg 이상에서 순수 좌클릭                        → preventDefault 후 `?selected=` 로 클라이언트 전환
//
// href 자체는 항상 상세 페이지를 가리킨다 — no-JS/저사양 환경에서도 항상 유효한
// 목적지가 있어야 하기 때문이다(과제 지시의 "반대로 해도 좋다" 선택지).
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { MouseEvent, ReactNode } from "react";

const DESKTOP_QUERY = "(min-width: 1024px)";

export function EventRowLink({
  detailHref,
  selectedHref,
  ariaCurrent,
  className,
  children,
}: {
  /** lg 미만·JS 없음·새 탭일 때의 목적지 — 전체 상세 페이지. */
  detailHref: string;
  /** lg 이상 좌클릭 시 실제로 가는 곳 — 이 페이지에 남아 우측 패널만 바꾼다. */
  selectedHref: string;
  ariaCurrent: boolean;
  className: string;
  children: ReactNode;
}) {
  const router = useRouter();

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    // 가운데 클릭·Cmd/Ctrl/Shift/Alt 조합은 "새 탭에서 열기" 의도다 — 그 경우 브라우저
    // 기본 동작(전체 상세 페이지를 새 탭에)을 건드리지 않는다.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    if (!window.matchMedia(DESKTOP_QUERY).matches) return;
    event.preventDefault();
    router.push(selectedHref, { scroll: false });
  }

  return (
    <Link
      href={detailHref}
      aria-current={ariaCurrent ? "true" : undefined}
      className={className}
      onClick={handleClick}
    >
      {children}
    </Link>
  );
}
