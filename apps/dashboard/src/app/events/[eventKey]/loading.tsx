import { SkeletonBlock, SkeletonList } from "@/components/ui/Skeleton";

export default function EventDetailLoading() {
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <SkeletonBlock className="h-24" />
      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-5 xl:grid-cols-[minmax(0,1fr)_396px]">
        <div className="flex flex-col gap-4 lg:col-start-2">
          <SkeletonBlock className="h-24" />
          <SkeletonBlock className="h-56" />
        </div>
        <div className="lg:col-start-1 lg:row-start-1">
          <SkeletonList rows={3} />
        </div>
      </div>
    </div>
  );
}
