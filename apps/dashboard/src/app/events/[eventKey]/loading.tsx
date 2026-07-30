import { SkeletonBlock, SkeletonList } from "@/components/ui/Skeleton";

export default function EventDetailLoading() {
  return (
    <div className="flex flex-col gap-6 p-4 sm:p-6">
      <SkeletonBlock className="h-28" />
      <SkeletonBlock className="h-40" />
      <SkeletonList rows={3} />
    </div>
  );
}
