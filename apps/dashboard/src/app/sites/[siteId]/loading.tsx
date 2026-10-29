import { SkeletonBlock, SkeletonList } from "@/components/ui/Skeleton";

export default function SiteDetailLoading() {
  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5 lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-5 xl:grid-cols-[minmax(0,1fr)_396px]">
      <div className="flex flex-col gap-5">
        <div className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px] leading-5 text-ink-2">
          <p>현장 화면을 불러오는 중입니다. 계속 이 화면이 보이면 연결을 확인하고 새로고침하세요.</p>
          <noscript><p className="mt-2">이 화면을 사용하려면 브라우저에서 자바스크립트를 켜고 새로고침하세요.</p></noscript>
        </div>
        <SkeletonBlock className="h-24" />
        <div className="flex flex-col gap-3">
          <SkeletonBlock className="h-6 w-32" />
          <SkeletonList rows={3} />
        </div>
        <div className="flex flex-col gap-3">
          <SkeletonBlock className="h-6 w-32" />
          <SkeletonList rows={3} />
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <SkeletonBlock className="h-56" />
        <SkeletonBlock className="h-48" />
      </div>
    </div>
  );
}
