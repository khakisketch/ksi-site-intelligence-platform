import Link from "next/link";

export default function MissionNotFound() {
  return (
    <div className="flex flex-col items-center gap-3 p-10 text-center">
      <p className="text-base font-medium break-keep">임무를 찾을 수 없습니다</p>
      <p className="max-w-sm text-sm break-keep text-ink-2">
        요청한 임무 ID가 존재하지 않거나 삭제되었습니다.
      </p>
      <Link href="/missions" className="btn btn-primary mt-2">
        임무 목록으로
      </Link>
    </div>
  );
}
