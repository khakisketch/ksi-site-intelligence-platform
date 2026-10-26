import { NextResponse, type NextRequest } from "next/server";

import {
  DeltaPublicationRequestError,
  DeltaUpstreamTimeoutError,
  isOpaquePublicationId,
  isScopeId,
  parseDeltaChunkRange,
  readDeltaPublicationBytes,
} from "@/lib/core-api/delta-publications";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export const dynamic = "force-dynamic";

function singleQuery(url: URL, name: "offset" | "length"): string | null {
  const values = url.searchParams.getAll(name);
  if (values.length !== 1) return null;
  return values[0] ?? null;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; publicationId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId: rawSiteId, workAreaId: rawWorkAreaId, publicationId: rawPublicationId } = await params;
    const siteId = decodeURIComponent(rawSiteId);
    const workAreaId = decodeURIComponent(rawWorkAreaId);
    const publicationId = decodeURIComponent(rawPublicationId);
    if (!isScopeId(siteId) || !isScopeId(workAreaId) || !isOpaquePublicationId(publicationId)) {
      return NextResponse.json({ message: "차분 파일 식별자가 올바르지 않습니다." }, { status: 400 });
    }
    const url = new URL(request.url);
    const rawOffset = singleQuery(url, "offset");
    const rawLength = singleQuery(url, "length");
    const offset = rawOffset !== null && /^\d+$/.test(rawOffset) ? Number(rawOffset) : Number.NaN;
    const length = rawLength !== null && /^\d+$/.test(rawLength) ? Number(rawLength) : Number.NaN;
    const range = parseDeltaChunkRange(offset, length);
    return NextResponse.json(await readDeltaPublicationBytes(siteId, workAreaId, publicationId, range));
  } catch (error) {
    if (error instanceof DeltaPublicationRequestError) {
      return NextResponse.json({ message: error.message }, { status: 400 });
    }
    if (error instanceof DeltaUpstreamTimeoutError) {
      return NextResponse.json(
        { message: "차분 파일 서버의 응답이 지연됩니다. 수치 결과에는 영향이 없으며, 잠시 후 상태를 확인하세요." },
        { status: 503 },
      );
    }
    return coreApiErrorResponse(error);
  }
}
