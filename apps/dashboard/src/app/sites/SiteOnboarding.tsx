import Link from "next/link";

import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import type { SiteRegistrationAvailability } from "@/lib/core-api/permissions";

/**
 * 현장 목록이 비어 있을 때 나온다. Core 목록은 현재 계정의 접근 범위로
 * 제한되므로 조직 전체에 등록된 현장이 없다고 단정하지 않는다.
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
        <h2 className="text-[22px] font-bold tracking-tight break-keep">
          현재 계정에서 볼 수 있는 현장이 없습니다
        </h2>
        <p className="max-w-xl text-[13px] break-keep text-ink-2">
          찾는 현장이 이미 있다면 관리자에게 이 계정의 현장 접근 권한을 확인해 주세요.
        </p>
        <p className="max-w-xl text-[13px] break-keep text-ink-2">
          새 현장이 필요하면 현장을 등록한 뒤 작업구역과 관측 자료를 확인할 수 있습니다.
        </p>
      </div>

      {availability.status === "allowed" ? (
        <Link href="/sites/new" className="btn btn-primary tap-target">
          현장 등록하기
        </Link>
      ) : availability.status === "unavailable" ? (
        <ActionUnavailable
          label="현장 등록하기"
          description="등록 권한을 확인하지 못했습니다. 잠시 후 다시 확인하세요."
          retry
        />
      ) : (
        <ActionUnavailable
          label="현장 등록하기"
          description="현재 계정으로는 현장을 등록할 수 없습니다. 관리자에게 문의하세요."
        />
      )}
    </section>
  );
}
