"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { StateBadge } from "@/components/ui/StatusBadge";
import { TableAction, TableRow, TableShell } from "@/components/ui/TableShell";

import {
  PORTFOLIO_SORTS,
  type PortfolioRow,
  type PortfolioSort,
  derivePortfolio,
  normalizePortfolioSort,
} from "./portfolio";

// 고정폭 열 합(410) + 간격(40) + 좌우 여백(32) + 현장 열 최소폭(150) = 632.
// `minWidth` 를 그 합보다 크게 잡으면 넉넉한 화면에서도 가로 스크롤바가 생긴다 —
// 1440 렌더 확인에서 실제로 그랬다(왼쪽 단 폭 ≈ 697px, 예전 값 700).
const COLUMNS = "minmax(150px,1.4fr) 118px 76px 88px 128px";
const MIN_WIDTH = 632;

const SHORT_DATE = new Intl.DateTimeFormat("ko-KR", {
  month: "numeric",
  day: "numeric",
  timeZone: "Asia/Seoul",
});

function shortDate(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? iso : SHORT_DATE.format(when);
}

/**
 * 현장 포트폴리오 표 — 홈의 본문(Console v2 §1).
 *
 * ── 왜 클라이언트에서 거르는가 ─────────────────────────────────────────
 * 검색어와 정렬은 **URL 이 정본**이다(공유·새로고침·뒤로가기가 같은 화면을 낸다).
 * 다만 그 URL 을 라우터로 바꾸면 글자 하나마다 서버 컴포넌트가 다시 돌고 Core API
 * 를 다시 두드린다 — 이 앱의 fetch 는 `no-store` 라 정말 매번 나간다.
 *
 * 그래서 값 갱신은 `window.history.replaceState` 로 한다(Next 가 공식 지원하는
 * 경로 — 라우터 상태와 동기화되지만 재요청은 하지 않는다). 행 데이터는 이미 서버가
 * 전부 실어 보냈고 여기서 하는 일은 **거르기와 정렬뿐**이라, 지어내는 값이 생길
 * 여지가 없다(판정 로직은 `portfolio.ts` 의 순수 함수 — 회귀는 그쪽에서 잡는다).
 *
 * 첫 상태는 서버가 읽은 URL 값(`initialQuery`/`initialSort`)에서 온다 —
 * `useSearchParams` 를 쓰지 않으므로 이 컴포넌트는 Suspense 경계를 요구하지 않는다.
 */
export function PortfolioTable({
  rows,
  initialQuery,
  initialSort,
  meta,
}: {
  rows: PortfolioRow[];
  initialQuery: string;
  initialSort: string;
  meta: string;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [sort, setSort] = useState<PortfolioSort>(() => normalizePortfolioSort(initialSort));

  const visible = useMemo(() => derivePortfolio(rows, query, sort), [rows, query, sort]);

  function syncUrl(nextQuery: string, nextSort: PortfolioSort) {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (nextQuery.trim()) params.set("q", nextQuery.trim());
    else params.delete("q");
    if (nextSort !== "attention") params.set("sort", nextSort);
    else params.delete("sort");
    const search = params.toString();
    // replaceState 다 — 글자 하나마다 히스토리가 쌓이면 뒤로가기가 검색어를 되감는
    // 버튼이 되어 화면 밖으로 나가지 못한다.
    window.history.replaceState(null, "", search ? `?${search}` : window.location.pathname);
  }

  return (
    <TableShell
      title="현장 포트폴리오"
      meta={meta}
      actions={
        <>
          <label className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-[12px] text-ink-2 focus-within:border-line-strong">
            <svg
              aria-hidden="true"
              width="12"
              height="12"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
            >
              <circle cx="7" cy="7" r="4.4" />
              <path d="M10.4 10.4 14 14" />
            </svg>
            <input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                syncUrl(event.target.value, sort);
              }}
              placeholder="현장 검색"
              aria-label="현장 검색"
              className="w-24 bg-transparent text-[12px] outline-none"
            />
          </label>
          <select
            value={sort}
            onChange={(event) => {
              const next = normalizePortfolioSort(event.target.value);
              setSort(next);
              syncUrl(query, next);
            }}
            aria-label="정렬 기준"
            className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink-2"
          >
            {PORTFOLIO_SORTS.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </>
      }
    >
      <TableRow columns={COLUMNS} minWidth={MIN_WIDTH} head>
        <span>현장</span>
        <span>마지막 임무 발급</span>
        <span className="text-right">미조치</span>
        <span>등록일</span>
        <span className="text-right">바로가기</span>
      </TableRow>

      {visible.length === 0 ? (
        <p className="px-4 py-8 text-center text-[12.5px] break-keep text-ink-muted">
          검색과 일치하는 현장이 없습니다.
        </p>
      ) : (
        visible.map((row) => {
          const status = SITE_STATUS_LABEL[row.status];
          return (
            <TableRow key={row.siteId} columns={COLUMNS} minWidth={MIN_WIDTH}>
              <span className="min-w-0">
                <span className="flex items-center gap-1.5">
                  <Link
                    href={`/sites/${encodeURIComponent(row.siteId)}`}
                    className="min-w-0 truncate text-[13px] font-semibold hover:underline"
                  >
                    {row.name}
                  </Link>
                  <StateBadge label={status.label} tone={status.tone} />
                </span>
                <span className="num block truncate text-[10.5px] text-ink-muted">{row.siteId}</span>
              </span>

              {/* "마지막 조사"가 아니라 **발급**이다 — 이 시스템은 비행이 실제로
                  끝났는지를 이 목록만으로는 알지 못한다. 열 이름과 값이 같은 사실을
                  말해야 운영자가 이 표를 근거로 쓸 수 있다. */}
              <span className="num text-[12px] whitespace-nowrap">
                {row.lastMissionAt ? shortDate(row.lastMissionAt) : <span className="text-ink-muted">발급 없음</span>}
              </span>

              <span
                className={`num text-right text-[12px] font-bold ${
                  (row.unattendedCount ?? 0) > 0 ? "text-crit" : "text-ink-2"
                }`}
              >
                {row.unattendedCount ?? "—"}
              </span>

              <span className="num text-[11.5px] whitespace-nowrap text-ink-2">
                {shortDate(row.registeredAt)}
              </span>

              <span className="flex justify-end gap-1.5">
                {row.primaryAction && (
                  <ResponsiveActionBoundary
                    action={row.primaryAction.responsiveAction}
                    reason="현장 범위 설정과 조사 계획은 노트북의 전체 Operations Console에서 수행합니다."
                  >
                    <TableAction
                      href={row.primaryAction.href}
                      label={row.primaryAction.label}
                      primary
                    />
                  </ResponsiveActionBoundary>
                )}
                <TableAction href={`/world?siteId=${encodeURIComponent(row.siteId)}`} label="World" />
              </span>
            </TableRow>
          );
        })
      )}
    </TableShell>
  );
}
