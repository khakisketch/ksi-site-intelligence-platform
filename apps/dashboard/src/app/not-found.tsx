import { EmptyState } from "@/components/ui/EmptyState";

// app/not-found.tsx — 세그먼트 notFound() 호출과 미매칭 URL 전체를 함께 받는다
// (node_modules/next/dist/docs 의 not-found.md 확인, props 없음).
export default function NotFound() {
  return (
    <div className="p-4 sm:p-5">
      <EmptyState
        title="페이지를 찾을 수 없습니다"
        description="주소가 바뀌었거나 더 이상 존재하지 않는 화면입니다."
        action={{ label: "홈으로", href: "/" }}
      />
    </div>
  );
}
