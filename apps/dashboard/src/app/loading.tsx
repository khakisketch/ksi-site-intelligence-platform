import { SkeletonBlock } from "@/components/ui/Skeleton";

// Home은 현장·이벤트·작업 원장을 병렬 조회하는 async Server Component다. UX 목표 §3.5에
// 따라 spinner만 보이지 않고, "최우선 행동 → 현장 맥락 목록 → 현장 현황"의 실제 높이를
// 미리 보여 준다. 포트폴리오 표를 흉내 낸 큰 skeleton은 더 이상 Home에 두지 않는다.
export default function HomeLoading() {
  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <SkeletonBlock className="h-10 w-44" />
      <SkeletonBlock className="h-[132px]" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.9fr)]">
        <div className="flex flex-col gap-4">
          {Array.from({ length: 2 }).map((_, index) => (
            <SkeletonBlock key={index} className="h-[180px]" />
          ))}
        </div>
        <div className="flex flex-col gap-4">
          <SkeletonBlock className="h-[92px]" />
          <SkeletonBlock className="h-[228px]" />
        </div>
      </div>
    </div>
  );
}
