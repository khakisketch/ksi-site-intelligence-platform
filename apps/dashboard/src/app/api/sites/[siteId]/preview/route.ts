import { NextResponse, type NextRequest } from "next/server";

import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { getSpatialAsset } from "@/lib/core-api/spatial-assets";
import {
  listSpatialDataRequests,
  type SpatialDataJobView,
} from "@/lib/core-api/spatial-data-requests";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import {
  buildSitePreviewDescriptor,
  pickAreaPreviewJob,
  SITE_PREVIEW_MAX_AREAS,
  SITE_PREVIEW_MAX_REQUEST_PAGES,
  SITE_PREVIEW_REQUESTS_PER_AREA,
  type SitePreviewLookup,
} from "@/lib/site-preview";

/** 경로 세그먼트에 들어갈 수 없는 문자 — Core 호출 전에 404로 끊는다. */
const SITE_ID_PATTERN = /^[^/\\?#\s\x00-\x1f\x7f@]+$/;

/**
 * 현장 목록 미리보기용 읽기 전용 기술서(BFF 집계).
 *
 * 같은 세션의 권한으로 Core를 읽는다 — 구역 목록, 구역별 bounded 요청
 * 목록, 선택된 요청의 자산 상세 순이며, 구역·요청·자산 어느 한 번이라도
 * 거부·없음이면 그 자리에서 멈추고 Core 판정을 그대로 돌려준다(403/404를
 * opaque하게 전달하고, 바이트·서명 URL·원본 키를 절대 내보내지 않는다).
 * 파일 바이트는 이 경로가 주지 않는다 — 준비 파일 BFF가 매번 다시 대조한다.
 * 응답은 private/no-store 다. 요청 간 공유 캐시가 없으며, 만료·회수된 출력은
 * 후보에서 빠진다.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    if (!SITE_ID_PATTERN.test(siteId)) {
      return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    }

    const areas = await listWorkAreas(siteId);
    const scannedAreas = areas.workAreas.slice(0, SITE_PREVIEW_MAX_AREAS);
    // 묶음 밖 구역은 훑지 않으므로, 후보가 없어도 없음이 아니라 미확인이다.
    let sawUnknown = areas.workAreas.length > scannedAreas.length;
    const pending = scannedAreas.map((area) => ({ area, cursor: undefined as string | undefined, seen: new Set<string>() }));
    for (let calls = 0; pending.length > 0 && calls < SITE_PREVIEW_MAX_REQUEST_PAGES; calls += 1) {
      const scan = pending.shift()!;
      const { area } = scan;
      let jobs: SpatialDataJobView[];
      try {
        const page = await listSpatialDataRequests(siteId, area.workAreaId, {
          limit: SITE_PREVIEW_REQUESTS_PER_AREA,
          ...(scan.cursor ? { cursor: scan.cursor } : {}),
        });
        if (!Array.isArray(page.items) || page.items.length > SITE_PREVIEW_REQUESTS_PER_AREA) {
          sawUnknown = true;
          continue;
        }
        jobs = page.items;
        if (page.nextCursor !== null) {
          if (typeof page.nextCursor !== "string" || page.nextCursor.length === 0
            || page.nextCursor.length > 2048 || scan.seen.has(page.nextCursor)) {
            sawUnknown = true;
          } else {
            scan.seen.add(page.nextCursor);
            // Existing area pages go first; unused calls then follow opaque Core
            // continuations. Never decode/forge cursors or expand the total budget.
            pending.push({ ...scan, cursor: page.nextCursor });
          }
        }
      } catch {
        // 이 구역의 목록을 못 읽으면 다음 구역으로 — 전체 판정은 unknown이다.
        sawUnknown = true;
        continue;
      }
      const job = pickAreaPreviewJob(jobs, { siteId, workAreaId: area.workAreaId });
      if (!job || !job.receipt) {
        continue;
      }
      let asset = null;
      try {
        const detail = await getSpatialAsset(siteId, area.workAreaId, job.assetRef);
        // 자산 상세가 요청한 식별자와 어긋나면 라벨에 쓰지 않는다 — 픽셀 자격은
        // 영수증+파일 BFF가 어차피 다시 대조한다.
        if (
          detail.assetRef === job.assetRef &&
          detail.siteId === siteId &&
          detail.workAreaId === area.workAreaId
        ) {
          asset = {
            revision: detail.revision,
            gsdM: detail.declared.gsdM,
            captureStartedAt: detail.declared.captureStartedAt,
            captureEndedAt: detail.declared.captureEndedAt,
            captureDate: detail.declared.captureDate ?? null,
            attribution: null,
          };
        }
      } catch {
        // 자산 상세 실패는 라벨만 미상으로 — 픽셀 자격은 영수증+파일 BFF가 정한다.
        asset = null;
      }
      const descriptor = buildSitePreviewDescriptor({
        siteId,
        area: { workAreaId: area.workAreaId, name: area.name },
        job,
        receipt: job.receipt,
        asset,
      });
      return NextResponse.json(descriptor satisfies SitePreviewLookup, {
        headers: { "Cache-Control": "private, no-store" },
      });
    }

    const lookup: SitePreviewLookup = sawUnknown || pending.length > 0
      ? { available: false, reason: "unknown" }
      : { available: false, reason: "no-output" };
    return NextResponse.json(lookup, {
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
