import { SkeletonBlock, SkeletonList } from "@/components/ui/Skeleton";

export default function EventsLoading() {
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {/* 대기열 4칸 스켈레톤 */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonBlock key={i} className="h-16" />
        ))}
      </div>
      <SkeletonBlock className="h-9 w-full max-w-md" />
      {/* page.tsx 의 lg 2열(목록·상세)과 같은 그리드 — 로딩 중에도 레이아웃이
          널뛰지 않게 한다. 상세 칸은 lg 미만에서 렌더되지 않는 실제 화면과 맞춰 숨긴다. */}
      <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-5 xl:grid-cols-[minmax(0,1fr)_396px]">
        <SkeletonList rows={6} />
        <SkeletonBlock className="hidden h-[420px] lg:block" />
      </div>
    </div>
  );
}
