import { SkeletonBlock } from "@/components/ui/Skeleton";

// 홈은 4개 Core API를 병렬 호출하는 async Server Component라 첫 진입 시 지연이 생길 수 있다.
// UX 목표 §3.5 — spinner 단독 금지, 콘텐츠 크기를 예고하는 skeleton으로 레이아웃 점프를 막는다.
// 4단 위계(콜아웃 → 지표 타일 4열 → 현장 카드 그리드 → 타임라인)를 그대로 예고한다 —
// 균일한 블록 5개는 실제 레이아웃과 모양이 달라 스켈레톤이 있으나 마나였다.
export default function HomeLoading() {
  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      <SkeletonBlock className="h-[76px]" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonBlock key={i} className="h-[74px]" />
        ))}
      </div>
      <div className="flex flex-col gap-3">
        <SkeletonBlock className="h-4 w-32" />
        <div className="grid grid-cols-[repeat(auto-fit,minmax(238px,1fr))] gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonBlock key={i} className="h-[132px]" />
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-3">
        <SkeletonBlock className="h-4 w-40" />
        <SkeletonBlock className="h-[220px]" />
      </div>
    </div>
  );
}
