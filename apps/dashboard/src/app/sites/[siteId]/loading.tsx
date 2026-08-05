import { SkeletonBlock, SkeletonList } from "@/components/ui/Skeleton";

export default function SiteDetailLoading() {
  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5 lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-5 xl:grid-cols-[minmax(0,1fr)_396px]">
      <div className="flex flex-col gap-5">
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
