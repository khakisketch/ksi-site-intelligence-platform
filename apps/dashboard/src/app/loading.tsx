import { SkeletonBlock } from "@/components/ui/Skeleton";

// 홈은 4개 Core API를 병렬 호출하는 async Server Component라 첫 진입 시 지연이 생길 수 있다.
// UX 목표 §3.5 — spinner 단독 금지, 콘텐츠 크기를 예고하는 skeleton으로 레이아웃 점프를 막는다.
export default function HomeLoading() {
  return (
    <div className="flex flex-col gap-6 p-4 sm:p-6 lg:p-8">
      <div className="flex flex-col gap-2">
        <SkeletonBlock className="h-6 w-24" />
        <SkeletonBlock className="h-4 w-64" />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonBlock key={i} className="h-48" />
        ))}
      </div>
    </div>
  );
}
