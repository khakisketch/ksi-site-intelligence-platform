import Link from "next/link";

/**
 * 표 한 장의 껍데기 — 제목줄 + 가로 스크롤 영역(Console v2 §1·§2 공용).
 *
 * **열 추상화를 만들지 않는다.** 컬럼 정의 배열로 표를 그리는 헬퍼는 화면마다
 * 다른 셀(배지·링크 두 개·mono 수치)을 결국 조건분기로 되받아, 표 하나 고치려고
 * 공용 헬퍼를 고치게 만든다. 여기서 공유하는 것은 **틀과 격자 폭**뿐이고 셀
 * 내용은 각 화면이 직접 쓴다.
 *
 * 격자 폭(`columns`)과 최소 폭(`minWidth`)을 헤더행과 본문행이 **같은 값**으로
 * 받는 것이 이 파일의 존재 이유다 — 두 곳에 따로 적히면 열이 어긋나고, 어긋난
 * 표는 화면을 보고서는 못 고친다(스크롤 위치에 따라 달라 보인다).
 */
export function TableShell({
  title,
  meta,
  actions,
  children,
}: {
  title: string;
  /** 제목 옆 한 줄 — 이 표가 무엇을 세고 있는지의 범위. */
  meta?: React.ReactNode;
  /** 검색·정렬 같은 조작부. 오른쪽 끝에 붙는다. */
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 border-b border-line px-4 py-2.5">
        <h2 className="text-[14px] font-bold tracking-tight break-keep">{title}</h2>
        {meta && <span className="text-[11.5px] break-keep text-ink-muted">{meta}</span>}
        {actions && <span className="ml-auto flex flex-wrap items-center gap-2">{actions}</span>}
      </div>
      {/* 가로 스크롤은 **표 안에서만** 일어난다 — 본문 전체가 옆으로 밀리면
          사이드바·상단바까지 따라 움직여 화면 전체가 흔들린다. */}
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

/**
 * 표의 한 줄. `head` 는 열 이름 줄이다.
 *
 * 행 전체를 링크로 감싸지 않는다 — 행 안에 이동 버튼이 따로 있는 표에서 링크가
 * 겹치면(중첩 `<a>`) 브라우저가 마크업을 임의로 고쳐 클릭 대상이 예측 불가능해진다.
 * 대신 각 화면이 셀 안에서 필요한 곳만 링크로 만든다.
 */
export function TableRow({
  columns,
  minWidth,
  head = false,
  children,
}: {
  columns: string;
  minWidth: number;
  head?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{ gridTemplateColumns: columns, minWidth }}
      className={
        head
          ? "grid items-center gap-2.5 border-b border-line bg-sunk px-4 py-2 text-[11px] font-bold break-keep text-ink-muted"
          : "grid items-center gap-2.5 border-b border-line px-4 py-2.5 text-[12.5px] transition-colors last:border-b-0 hover:bg-sunk"
      }
    >
      {children}
    </div>
  );
}

/** 표 안에서 쓰는 작은 이동 버튼 — 행마다 두세 개가 붙어도 시끄럽지 않은 크기. */
export function TableAction({
  href,
  label,
  primary = false,
}: {
  href: string;
  label: string;
  primary?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`tap-target inline-flex items-center rounded-md border px-2.5 text-[11.5px] font-semibold whitespace-nowrap transition-colors ${
        primary
          ? "border-line-strong bg-surface hover:border-accent hover:bg-accent hover:text-accent-on"
          : "border-line-strong bg-surface hover:bg-sunk"
      }`}
    >
      {label}
    </Link>
  );
}
