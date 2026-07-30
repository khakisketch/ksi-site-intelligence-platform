import { SkeletonBlock, SkeletonList } from "@/components/ui/Skeleton";

export default function SiteDetailLoading() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8 p-6 sm:p-10">
      <SkeletonBlock className="h-40" />
      <div className="flex flex-col gap-3">
        <SkeletonBlock className="h-6 w-32" />
        <SkeletonList rows={3} />
      </div>
      <div className="flex flex-col gap-3">
        <SkeletonBlock className="h-6 w-32" />
        <SkeletonList rows={3} />
      </div>
    </div>
  );
}
