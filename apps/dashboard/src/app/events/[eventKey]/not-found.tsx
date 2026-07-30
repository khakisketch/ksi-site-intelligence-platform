import { EmptyState } from "@/components/ui/EmptyState";

export default function EventNotFound() {
  return (
    <div className="p-4 sm:p-6">
      <EmptyState
        title="이벤트를 찾을 수 없습니다"
        description="삭제되었거나 잘못된 링크일 수 있습니다."
        action={{ label: "이벤트 목록으로", href: "/events" }}
      />
    </div>
  );
}
