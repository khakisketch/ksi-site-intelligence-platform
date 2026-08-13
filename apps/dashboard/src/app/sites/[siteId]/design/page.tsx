import Link from "next/link";
import { notFound } from "next/navigation";

import { CoreApiError } from "@/lib/core-api/client";
import { listDesignSurfaces } from "@/lib/core-api/design";
import { humanizeApiError } from "@/lib/core-api/labels";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getSite } from "@/lib/core-api/sites";
import { ErrorState } from "@/components/ui/ErrorState";
import type { DesignSurface, SiteView } from "@/lib/core-api/types";

import { DesignSurfacePanel } from "./DesignSurfacePanel";

/**
 * 설계 기준면 등록 화면 — "설계대로 되고 있나"를 물을 수 있게 만드는 첫 단계.
 *
 * 이 화면의 규율 하나: **사용자가 적어 낸 것과 서버가 파일에서 읽어낸 것을 끝까지
 * 갈라 보여준다.** 등록 폼의 값은 전부 주장이고(누구도 확인하지 않았다), 대조표의
 * 관측 열만이 확인된 사실이다. 둘을 한 줄로 합치면 잘못된 설계면으로 낸 잔량
 * 숫자가 "확인된 값"처럼 보이게 된다.
 */
export default async function SiteDesignPage({
  params,
}: {
  params: Promise<{ siteId: string }>;
}) {
  const { siteId } = await params;

  let site: SiteView | null = null;
  let errorMessage: string | null = null;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  if (errorMessage !== null || site === null) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState message={errorMessage ?? "요청을 처리하지 못했습니다."} />
      </div>
    );
  }

  // 목록·권한 조회는 서로 독립이다 — 목록이 실패해도 등록 폼은 살아 있어야 한다
  // (그때는 빈 목록으로 시작하고, 등록 직후 폴링이 실제 상태를 다시 채운다).
  const [surfacesResult, canWriteResult] = await Promise.allSettled([
    listDesignSurfaces(site.siteId),
    hasAllPermissions("SITES_WRITE"),
  ]);
  const surfaces: DesignSurface[] =
    surfacesResult.status === "fulfilled" ? surfacesResult.value.surfaces : [];
  const canWrite = canWriteResult.status === "fulfilled" && canWriteResult.value;

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <Link
          href={`/sites/${encodeURIComponent(site.siteId)}`}
          className="text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
        >
          ← {site.name}
        </Link>
        <h1 className="break-keep text-[19px] font-bold tracking-tight">설계 기준면</h1>
        <p className="max-w-2xl text-[12.5px] break-keep text-ink-2">
          완성된 지형의 계획고를 담은 높이 자료(GeoTIFF)를 올려두면, 이후 촬영한
          현재 지형과 견줘 <strong className="font-bold">구역별로 얼마나 더 깎고 더
          쌓아야 하는지</strong>를 계산할 수 있습니다.
        </p>
      </div>

      <DesignSurfacePanel
        siteId={site.siteId}
        siteCrs={site.siteFrame.crs}
        canWrite={canWrite}
        initialSurfaces={surfaces}
      />
    </div>
  );
}
