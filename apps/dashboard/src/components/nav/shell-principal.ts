import "server-only";

import { cache } from "react";

import { whoAmI } from "@/lib/core-api/auth";

/**
 * 셸의 두 자리(상단바의 세션 안내·좁은 화면 계정 버튼, 레일 아래쪽 계정 메뉴)가 같은 신원을 쓴다.
 * 요청마다 한 번만 읽도록 묶는다 — 두 곳이 따로 읽으면 같은 화면에서 서로 다른 응답을 볼 수 있다.
 */
export const readShellPrincipal = cache(() => whoAmI());
