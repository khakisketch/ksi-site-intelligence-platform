import Link from "next/link";

import { AccountDisplayBoundary } from "@/components/nav/AccountDisplayBoundary";
import { siteAreasHref } from "@/components/nav/site-context";
import { SectionFrame } from "@/components/section/SectionFrame";
import { whoAmI } from "@/lib/core-api/auth";
import { continuityFingerprint } from "@/lib/core-api/work-order-continuity";
import type { SiteView, WorkArea } from "@/lib/core-api/types";

import { WorkAreaPanel } from "../work-areas/WorkAreaPanel";
import { SpaceViewTabs } from "./SpaceViewTabs";
import type { WorkAreaListFailure } from "./work-area-list-failure";

/**
 * 공간의 영역 관리 보기(ADR-KSI-043) — 영역 추가·범위 바꾸기(새 영역으로 대체)·보관.
 *
 * 등록·대체·보관의 안전 장치(중복 제출 방지, 계정 연속성 확인, 미확인 제출 복구, 임시 기록)는
 * `WorkAreaPanel`이 그대로 맡는다. 이 보기는 그 패널을 공간 안에 놓는 틀일 뿐이다. 기하는 등록
 * 순간 굳으므로 수정 버튼은 없고, 이미 낸 결과가 이전 영역을 가리키는 규칙도 그대로다.
 *
 * 계정 연속성 확인값은 서버에서 확인한 두 식별자의 비교값일 뿐 자격 증명이나 인가가 아니다.
 * 확인하지 못하면 패널이 목록과 원문을 숨기고 재확인을 안내한다.
 */
export async function SpaceAreasManage({ site, workAreas, workAreaError, canWrite, selectedId }: {
  site: SiteView;
  workAreas: readonly WorkArea[];
  workAreaError: WorkAreaListFailure | null;
  canWrite: boolean;
  selectedId: string | null;
}) {
  const identity = await whoAmI().catch(() => null);
  const accountIdentity = (() => {
    const fingerprint = continuityFingerprint(identity);
    const permissions = identity?.permissions;
    const permissionsVerified =
      Array.isArray(permissions) && permissions.every((permission) => typeof permission === "string");
    return fingerprint && permissionsVerified ? { fingerprint } : null;
  })();
  const context = (
    <>
      <SpaceViewTabs sitePath={`/sites/${encodeURIComponent(site.siteId)}`} siteId={site.siteId} workAreaId={selectedId} />
      <section aria-label="영역 관리 안내" className="flex min-w-0 flex-col gap-2 px-1">
        <h2 className="text-micro font-bold tracking-wide text-ink-muted">영역 관리</h2>
        <p className="text-caption text-ink-2">자료를 연결하고 비교할 범위를 등록합니다. 범위를 바꾸려면 새 영역으로 대체하며, 기존 결과는 이전 영역을 계속 참조합니다.</p>
        <Link href={siteAreasHref(site.siteId, selectedId)} className="btn w-fit">지도로 보기</Link>
      </section>
    </>
  );
  return (
    <AccountDisplayBoundary fingerprint={accountIdentity?.fingerprint ?? null}>
      <SectionFrame contextLabel="영역 관리" context={context}>
        <WorkAreaPanel
          siteId={site.siteId}
          siteCrs={site.siteFrame.crs}
          canWrite={canWrite}
          initialWorkAreas={[...workAreas]}
          workAreaListError={workAreaError}
          accountIdentity={accountIdentity}
        />
      </SectionFrame>
    </AccountDisplayBoundary>
  );
}
