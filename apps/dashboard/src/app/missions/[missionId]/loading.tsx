import { SkeletonBlock } from "@/components/ui/Skeleton";

export default function MissionDetailLoading() {
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5" aria-busy="true" aria-label="불러오는 중">
      <div className="h-5 w-24 animate-pulse rounded bg-sunk" />
      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-2 lg:gap-5">
        <SkeletonBlock className="h-64" />
        <SkeletonBlock className="h-64" />
      </div>
    </div>
  );
}
