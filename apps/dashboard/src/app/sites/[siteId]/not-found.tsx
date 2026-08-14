import Link from "next/link";

export default function SiteNotFound() {
  // 로그인 카드처럼 본래 좁아야 하는 내용이라 폭 캡을 유지한다 — 여기서 없애야 하는
  // 건 전역 규칙이 말하는 '672px 문서'가 아니라 진짜로 좁아야 할 짧은 안내 카드다.
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 p-4 py-16 text-center sm:p-5 sm:py-20">
      <h2 className="text-[17px] font-bold break-keep">현장을 찾을 수 없습니다</h2>
      <p className="break-keep text-ink-2">요청한 현장 ID가 존재하지 않거나 삭제되었습니다.</p>
      <Link href="/sites" className="btn btn-primary mt-2">
        현장 목록으로
      </Link>
    </div>
  );
}
