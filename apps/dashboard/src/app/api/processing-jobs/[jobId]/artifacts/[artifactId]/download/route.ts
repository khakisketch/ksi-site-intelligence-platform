import { NextResponse, type NextRequest } from "next/server";

import { getProcessingArtifactDownloadUrl } from "@/lib/core-api/phase34";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 산출물(정사영상·DSM 등) 열람 URL 발급. 짧은 수명(분 단위)이라 **볼 때마다**
 * 새로 받는다 — evidence/[artifactId] 와 같은 규약(응답에 URL 을 미리 실어두면
 * 그 응답 자체가 유효기간 있는 인가가 된다).
 *
 * `verdict !== "ARTIFACT_READY"` 인 경우도 200으로 그대로 돌려준다 — 호출부
 * (지도 컴포넌트)가 "아직 없음"과 "발급 실패"를 구분해 빈 상태로 다룬다.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string; artifactId: string }> },
) {
  try {
    await getSessionToken();
    const { jobId, artifactId } = await params;
    const result = await getProcessingArtifactDownloadUrl(
      decodeURIComponent(jobId),
      decodeURIComponent(artifactId),
    );
    return NextResponse.json(result);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
