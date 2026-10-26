import { NextResponse, type NextRequest } from "next/server";

import {
  DeltaPublicationRequestError,
  DeltaUpstreamTimeoutError,
  getDeltaPublication,
  isDigest,
  isOpaquePublicationId,
  isScopeId,
} from "@/lib/core-api/delta-publications";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
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
    const source = {
      sourceCalculationIdentityDigest: "",
      sourceNumericResultIdentityDigest: "",
      sourceCoverageWitnessDigest: "",
    };
    // 상세 조회는 브라우저가 BFF 쿼리로 세 출처 확인값을 그대로 메아리한다.
    // 격자·좌표는 싣지 않으며, 서버 메아리 검증은 lib가 닫힌 형태로 수행한다.
    const url = new URL(_request.url);
    const digests = {
      sourceCalculationIdentityDigest: url.searchParams.get("sourceCalculationIdentityDigest"),
      sourceNumericResultIdentityDigest: url.searchParams.get("sourceNumericResultIdentityDigest"),
      sourceCoverageWitnessDigest: url.searchParams.get("sourceCoverageWitnessDigest"),
    };
    for (const [key, value] of Object.entries(digests) as [keyof typeof source, string | null][]) {
      if (!isDigest(value)) {
        throw new DeltaPublicationRequestError("출처 확인값 형식이 올바르지 않습니다.");
      }
      source[key] = value;
    }
    return NextResponse.json(await getDeltaPublication(siteId, workAreaId, publicationId, source));
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
