import Link from "next/link";

export default function SurveyNewNotFound() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center gap-3 p-10 text-center">
      <h1 className="text-lg font-medium break-keep">현장을 찾을 수 없습니다</h1>
      <p className="text-foreground/60 break-keep">
        새 조사를 시작하려는 현장 ID가 존재하지 않거나 삭제되었습니다.
      </p>
      <Link
        href="/sites"
        className="bg-foreground text-background mt-2 inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium"
      >
        현장 목록으로
      </Link>
    </div>
  );
}
