import Link from "next/link";

import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import type { SiteRegistrationAvailability } from "@/lib/core-api/permissions";

/**
 * 첫 실행 화면 — 등록된 현장이 0곳일 때만 나온다.
 *
 * 등록 진입은 RegisterSiteAction 과 같은 3상태 문구를 쓴다. 확인 실패를
 * 거부로 속이지 않는다: unavailable 은 재시도 버튼과 함께 미확인으로 보인다.
 */
export function SiteOnboarding({
  availability,
}: {
  availability: SiteRegistrationAvailability;
}) {
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col items-center gap-5 py-10 text-center">
      <div className="flex flex-col items-center gap-1.5">
        <p className="text-[11px] font-bold tracking-wider break-keep text-ink-muted">
          첫 실행 · 등록된 현장 0곳
        </p>
        <h2 className="text-[22px] font-bold tracking-tight break-keep">
          현장을 등록하면 여기서 시작합니다
        </h2>
        <p className="max-w-xl text-[13px] break-keep text-ink-2">
          현장 이름과 외곽 경계를 등록한 뒤, 현장 화면에서 작업구역과 등록된 플랫폼 기록을 확인할 수 있습니다.
        </p>
      </div>

      {availability.status === "allowed" ? (
        <Link href="/sites/new" className="btn btn-primary tap-target">
          첫 현장 등록하기
        </Link>
      ) : availability.status === "unavailable" ? (
        <ActionUnavailable
          label="첫 현장 등록하기"
          description="등록 권한을 확인하지 못했습니다. 잠시 후 다시 확인하세요."
          retry
        />
      ) : (
        <ActionUnavailable
          label="첫 현장 등록하기"
          description="현재 계정으로는 현장을 등록할 수 없습니다. 관리자에게 문의하세요."
        />
      )}
    </section>
  );
}
