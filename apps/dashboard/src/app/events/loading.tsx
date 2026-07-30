import { SkeletonList } from "@/components/ui/Skeleton";

export default function EventsLoading() {
  return (
    <div className="flex flex-col gap-6 p-4 sm:p-6">
      <div className="h-6 w-40 animate-pulse rounded bg-black/5 dark:bg-white/10" />
      <div className="h-20 animate-pulse rounded bg-black/5 dark:bg-white/10" />
      <SkeletonList rows={6} />
    </div>
  );
}
