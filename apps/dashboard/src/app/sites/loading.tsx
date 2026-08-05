import { SkeletonBlock } from "@/components/ui/Skeleton";

export default function SitesLoading() {
  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      <div className="flex items-center justify-between gap-4">
        <SkeletonBlock className="h-4 w-14" />
        <SkeletonBlock className="h-9 w-24" />
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(238px,1fr))] gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonBlock key={i} className="h-32" />
        ))}
      </div>
    </div>
  );
}
