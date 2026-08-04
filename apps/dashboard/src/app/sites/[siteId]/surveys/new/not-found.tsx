import Link from "next/link";

export default function SurveyNewNotFound() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center gap-3 p-4 text-center sm:p-5">
      {/* TopBar 가 이미 이 라우트의 h1("조사 계획")을 렌더한다 — 본문 "제목"은 p 로
          둔다(EmptyState.tsx 와 동일 관례, 페이지에 h1 을 중복시키지 않는다). */}
      <p className="text-[15px] font-bold break-keep text-ink-1">현장을 찾을 수 없습니다</p>
      <p className="break-keep text-ink-2">
        새 조사를 시작하려는 현장 ID가 존재하지 않거나 삭제되었습니다.
      </p>
      <Link href="/sites" className="btn btn-primary mt-2">
        현장 목록으로
      </Link>
    </div>
  );
}
