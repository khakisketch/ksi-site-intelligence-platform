import { NextResponse, type NextRequest } from "next/server";

import { getMissionKmz } from "@/lib/core-api/missions";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * KMZ 바이트 다운로드 — Core 가 저장된 요청으로 매 조회마다 재생성해 돌려준다
 * (바이트 자체는 저장하지 않는다). GET 이라 mutating 요청 전용 Origin 검사
 * (`isCrossSiteMutation`)는 적용하지 않는다 — 증거 열람 라우트(evidence/[artifactId])
 * 와 동일 관습.
 *
 * 세션 쿠키를 여기서 직접 확인하고, Core 호출은 이 값만 Authorization 으로 실어
 * 대행한다 — 고정 ADMIN 토큰으로 대행하던 risk
 * dashboard-unauthenticated-signing-proxy 를 재도입하지 않는다.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ missionId: string }> },
) {
  try {
    await getSessionToken();
    // Next 가 이미 디코드한 값이다 — 여기서 또 decodeURIComponent 하면 이중
    // 디코딩이다(임무 ID 문자셋상 무해하지만 사실이 아닌 코드는 남기지 않는다).
    const { missionId } = await params;
    const kmz = await getMissionKmz(missionId);
    return new NextResponse(kmz.body, {
      status: 200,
      headers: {
        "Content-Type": kmz.contentType,
        // 파일명은 Core 가 정한다 — 임무 ID 로 헤더를 조립하는 자리를 대시보드에
        // 두지 않는다. Core 가 헤더를 주지 않으면 임무 ID 를 끼워넣지 말고 고정
        // 이름으로 떨어뜨린다(검증되지 않은 값이 헤더가 되는 경로를 만들지 않는다).
        "Content-Disposition": kmz.contentDisposition ?? 'attachment; filename="mission.kmz"',
      },
    });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
