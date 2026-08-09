import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { hasAllPermissions } from "@/lib/core-api/permissions";

import { SiteRegistrationOnlyWizard } from "./SiteRegistrationOnlyWizard";
import { SiteRegistrationWizard } from "./SiteRegistrationWizard";

function ModeCard({
  href,
  title,
  description,
}: {
  href: string;
  title: string;
  description: string;
}) {
  return (
    <Link
      href={href}
      className="tap-target flex flex-1 flex-col gap-1.5 rounded-lg border border-line bg-surface p-4 text-left hover:border-line-strong hover:bg-sunk"
    >
      <span className="text-[14px] font-bold break-keep text-ink-1">{title}</span>
      <span className="text-[12.5px] break-keep text-ink-2">{description}</span>
    </Link>
  );
}

// ADR-KSI-015 이후 SITES_WRITE 를 가진 역할(ADMIN·FIELD_OPERATOR)은 항상
// MISSIONS_ISSUE 도 함께 갖는다 — 그래도 둘을 각각(AND) 요구한다(fail-closed).
// 표가 다시 갈라져도(예: 신규 역할 추가) 발급 권한 없이 임무 발급까지 요구하는
// 통합 흐름에 들어가는 반쪽 상태를 만들지 않기 위해서다.
//
// 예전엔 이 두 권한 보유 여부로 SiteRegistrationWizard(통합)/
// SiteRegistrationOnlyWizard(등록만) 를 **자동으로** 갈랐다 — 3역할 체계에서는
// 두 권한이 항상 같이 붙어 있어 그 분기가 도달 불가가 됐다(SITES_WRITE 를 가진
// 역할은 항상 MISSIONS_ISSUE 도 갖는다). "등록만 하고 임무는 나중"은 RBAC 의
// 산물이 아니라 도메인의 산물이다(UNMAPPED 가 정상 중간 상태) — 그래서 이제는
// 권한이 아니라 **사용자 선택**으로 두 흐름을 가른다.
export default async function NewSitePage({
  searchParams,
}: {
  searchParams: Promise<{ mode?: string }>;
}) {
  const canRegisterWithMission = await hasAllPermissions("SITES_WRITE", "MISSIONS_ISSUE");

  if (!canRegisterWithMission) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-6 p-4 sm:p-5">
        <EmptyState
          title="현장 등록 권한이 없습니다"
          description="현장 등록은 현장 등록·임무 발급 권한을 모두 가진 계정만 할 수 있습니다. 관리자에게 문의하세요."
        />
      </div>
    );
  }

  const { mode } = await searchParams;
  if (mode === "registration-only") return <SiteRegistrationOnlyWizard />;
  if (mode === "full") return <SiteRegistrationWizard />;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <p className="text-[10.5px] font-bold tracking-[0.1em] text-ink-muted uppercase break-keep">
          현장 등록
        </p>
        <h1 className="text-[17px] font-bold tracking-tight break-keep">
          베이스라인 임무까지 이어서 발급할까요?
        </h1>
        <p className="text-[13px] break-keep text-ink-2">
          어느 쪽을 골라도 나중에 언제든 임무를 발급할 수 있습니다 — 지금 정하는 건 이번
          흐름의 길이일 뿐입니다.
        </p>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <ModeCard
          href="/sites/new?mode=full"
          title="등록 + 베이스라인 임무 발급"
          description="현장 외곽(AOI)·촬영 계획까지 이어서 입력하고 바로 임무를 발급합니다."
        />
        <ModeCard
          href="/sites/new?mode=registration-only"
          title="등록만 먼저"
          description="현장 기본정보·좌표계만 등록합니다. 임무는 현장 상세 화면에서 나중에 발급할 수 있습니다."
        />
      </div>
      <Link
        href="/sites"
        className="text-[12.5px] font-semibold break-keep text-ink-2 underline-offset-2 hover:text-ink-1 hover:underline"
      >
        목록으로
      </Link>
    </div>
  );
}
