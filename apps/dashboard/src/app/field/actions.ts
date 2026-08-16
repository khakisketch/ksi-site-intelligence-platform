"use server";

import { redirect } from "next/navigation";

import { clearSessionToken } from "@/lib/core-api/session";

/**
 * 현장 화면 전용 로그아웃 — 세션만 버리고 **현장 화면 안에 남는다**.
 *
 * `login/actions.ts` 의 `logout()` 은 /login 으로 보낸다. 조종기에서는 그게 두 번
 * 나쁘다: ① 웹뷰가 리다이렉트를 삼키면 로그아웃 후 화면이 멈춘 것처럼 보이고,
 * ② 삼키지 않아도 다음 사람은 로그인한 뒤 /field 를 다시 찾아 들어와야 한다.
 * 조종기는 공용 장비라 "쓰고 넘기기"가 기본 동선이고, 그 동선이 화면 이동 두 번을
 * 요구하면 사람들은 그냥 로그아웃하지 않는다 — 그러면 다음 사람이 앞사람 계정으로
 * 임무를 다룬다.
 *
 * 임무 상세에서 눌러도 목록(/field)으로 보낸다. 로그아웃은 곧 장비를 넘긴다는 뜻이고,
 * 다음 사람이 이어서 볼 화면은 앞사람의 임무가 아니라 자기 임무 목록이다.
 * /field 는 세션이 없으면 인라인 로그인 폼을 그리므로(proxy.ts 의 PUBLIC_PATHS)
 * 그 한 번의 이동으로 "다음 사람 로그인 화면"이 완성된다.
 *
 * 세션 파기 자체는 `clearSessionToken` 하나뿐이다 — 쿠키 이름·속성을 여기서 다시
 * 적지 않는다.
 */
export async function fieldLogout(): Promise<void> {
  await clearSessionToken();
  redirect("/field");
}
