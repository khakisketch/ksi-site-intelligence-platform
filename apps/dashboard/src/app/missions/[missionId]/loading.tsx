import { SkeletonBlock } from "@/components/ui/Skeleton";

export default function MissionDetailLoading() {
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-6 lg:p-8">
      <div className="h-5 w-24 animate-pulse rounded bg-black/5 dark:bg-white/10" />
      <h1 className="text-lg font-semibold break-keep">임무 상세</h1>
      <SkeletonBlock className="h-96" />
    </div>
  );
}
