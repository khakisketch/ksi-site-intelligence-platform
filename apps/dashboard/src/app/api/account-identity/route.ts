import { NextResponse } from "next/server";

import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import {
  continuityFingerprint,
  fetchCurrentContinuityIdentity,
} from "@/lib/core-api/work-order-continuity";

/**
 * 현재 세션의 계정 연속성 지문 읽기 전용 조회.
 *
 * 용도: 같은 탭에서 계정이 바뀐 채로 열린 등록 화면이, 서버 렌더 prop(마운트
 * 시점 스냅샷)만으로 원래 입력을 표시할지 판단할 수 있게 한다. BFF 변이 가드의
 * 대체재가 아니다 — POST 허용 여부는 항상 변이 시점의 세션 토큰으로 BFF가
 * 판정한다. 이 응답만으로는 읽기 화면 프라이버시를 보장한다고 주장하지 않는다
 * (확인 시점 사이 공백이 있고, 포커스 복귀 때 재확인하는 best-effort다).
 *
 * 보안 경계:
 * - 세션 없이는 Core를 호출하지 않고 401로 끊는다.
 * - 호출자 본인의 지문(동일성 비교값)만 돌려준다 — 다른 신원·현장 존재 여부를
 *   노출하지 않으므로 INV-060 오라클이 되지 않는다. 이 지문은 무키 SHA-256이라
 *   역함수 계산은 어렵지만, 입력(도메인 상수·조직·actor)이 추측 가능하면 후보를
 *   넣어 대조하는 역추측이 가능하다. 따라서 지문은 자격 증명이 아니며, 인가
 *   근거가 아니고, 식별자 자체의 비밀성을 보장하지 않는다 — 같은 값인지만
 *   비교하는 용도로만 쓴다.
 * - 변이를 일으키지 않는다(읽기 전용 GET, Core whoami 조회만 한다).
 * - 저장하지 않으며(`private, no-store`) 응답 본문은 지문 하나뿐이다.
 */
export async function GET() {
  let token: string;
  try {
    token = await getSessionToken();
  } catch (error) {
    return coreApiErrorResponse(error);
  }
  try {
    const identity = await fetchCurrentContinuityIdentity(token);
    const fingerprint = continuityFingerprint(identity);
    if (!fingerprint) {
      return NextResponse.json(
        { message: "계정 정보를 확인하지 못했습니다." },
        { status: 500 },
      );
    }
    const response = NextResponse.json({ fingerprint });
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
