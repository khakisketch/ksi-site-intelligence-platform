import { SkeletonList } from "@/components/ui/Skeleton";

export default function MissionsLoading() {
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-6 lg:p-8">
      <h1 className="text-lg font-semibold break-keep">임무</h1>
      <SkeletonList rows={5} />
    </div>
  );
}
