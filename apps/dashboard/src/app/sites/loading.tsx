import { SkeletonList } from "@/components/ui/Skeleton";

export default function SitesLoading() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-6 sm:p-10">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-lg font-semibold break-keep">현장</h1>
      </div>
      <SkeletonList rows={5} />
    </div>
  );
}
