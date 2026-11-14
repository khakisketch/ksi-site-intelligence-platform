import { StepIndicator } from "@/components/ui/StepIndicator";

/**
 * 자료 등록 순서 — 등록 화면(`observations/new`)의 세 단계와 같은 이름을 쓴다.
 *
 * 빈 무대에서 "등록" 단추만 두면 누른 뒤 무엇을 하게 되는지 알 수 없다.
 * 여기에는 순서만 두고, 진행 상태·완료 여부는 말하지 않는다(그 사실은 작업
 * 화면이 맡는다).
 */
const STEPS = ["작업구역", "파일 제출", "검사 확인"] as const;

export function RegistrationPath({ className = "" }: { className?: string }) {
  return <StepIndicator steps={STEPS} label="자료 등록 순서" className={className} />;
}
