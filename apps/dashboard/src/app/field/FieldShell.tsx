import type { ReactNode } from "react";

import Link from "next/link";

import { LoginForm } from "@/app/login/LoginForm";
import { ROLE_LABEL } from "@/lib/core-api/labels";
import type { WhoAmIResponse } from "@/lib/core-api/types";

import { fieldLogout } from "./actions";
import { PilotBridgeProbe } from "./PilotBridgeProbe";

// 현장 화면의 껍데기 — 헤더와 인라인 로그인.
//
// 앱 셸(사이드바·상단바)은 /field 에서 벗겨져 있다(isChromelessPath). 그래서 이
// 화면은 "지금 누구로 로그인했나"를 스스로 말해야 한다. 조종기는 공용 장비고,
// 앞사람 계정으로 임무를 다루는 것이 이 제품에서 가장 조용한 사고 경로다 —
// 임무 발급·사진 등록의 주체가 실제 사람과 어긋난 채 원장에 남는다.
//
// 그래서 신원과 로그아웃은 접히지도, 스크롤로 사라지지도 않는 자리에 상시 둔다.
// 다만 **고정(sticky)하지는 않는다** — 조종기는 가로 배치라 세로가 짧고, 고정 헤더는
// 그 짧은 세로를 상시 먹는다. 셸을 벗은 이유가 화면을 되찾는 것이었는데 헤더를
// 붙박이로 두면 그 이득을 그대로 반납한다.

export function FieldHeader({
  principal,
  children,
}: {
  principal: WhoAmIResponse;
  /** 헤더 아래 줄에 붙는 화면별 제목·부제. */
  children?: ReactNode;
}) {
  const roleLabel = principal.role ? ROLE_LABEL[principal.role] : principal.kind;

  return (
    <header className="flex flex-col gap-2 border-b border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="grid size-7 flex-none place-items-center rounded-md bg-accent text-[11px] font-extrabold tracking-tight text-accent-on"
          >
            KSI
          </span>
          <span className="text-[14px] font-bold tracking-tight break-keep">현장</span>
        </span>
        <span className="flex items-center gap-2">
          {/* 누구인지가 로그아웃 버튼보다 먼저 읽혀야 한다 — 버튼을 먼저 보면
              "로그아웃할 것인가"를 판단하기 전에 손이 먼저 간다. */}
          <span className="text-[13px] break-keep text-ink-2">
            <span className="font-semibold text-ink-1">{principal.principalId}</span> · {roleLabel}
          </span>
          <form action={fieldLogout}>
            <button type="submit" className="btn btn-field">
              로그아웃
            </button>
          </form>
        </span>
      </div>
      {children}
    </header>
  );
}

/**
 * 세션이 없을 때 /field 가 그리는 것 — 리다이렉트가 아니라 **이 화면**이다
 * (사유는 field-session.ts · proxy.ts 주석).
 *
 * 폼은 /login 의 것을 그대로 쓴다. 토큰 검증·시도 제한·오픈 리다이렉트 방어가 전부
 * 그 서버 액션에 있고, 현장용으로 한 벌 더 만들면 그 방어들이 두 곳에서 갈린다.
 */
export function FieldInlineLogin({
  next,
  notice,
}: {
  /** 로그인 성공 후 돌아올 경로 — 지금 보던 임무 화면 그대로. */
  next: string;
  notice: string | null;
}) {
  return (
    // field-controls — LoginForm 의 입력칸·버튼은 className 이 그 컴포넌트 안에
    // 고정돼 있다. 현장 치수는 밖에서 씌운다(globals.css 의 같은 이름 규칙 주석).
    <div className="field-controls flex flex-col gap-4 p-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-[17px] font-bold tracking-tight break-keep">현장 화면 로그인</h1>
        <p className="text-[13px] break-keep text-ink-2">
          이 조종기는 여러 사람이 함께 씁니다 — 임무를 다루기 전에 본인 토큰으로
          로그인하세요.
        </p>
      </div>
      {notice && (
        <p
          role="status"
          className="rounded-md bg-high-bg px-3 py-2 text-[13px] font-semibold break-keep text-high-ink"
        >
          {notice}
        </p>
      )}
      <div className="rounded-lg border border-line bg-surface p-4">
        <LoginForm next={next} />
      </div>
    </div>
  );
}

/**
 * 로그인으로 풀리지 않는 실패 — 폼을 보여주면 운영자가 자기 토큰을 의심하게 된다.
 *
 * 이 경로는 대개 "Core 미도달"이다(field-session.ts `classifyFieldSessionFailure`의
 * `unreachable`·알 수 없는 상태코드) — 현장에서 가장 흔한 실패 모드다. 그런데도
 * 예전에는 문장 두 줄 뒤에 운영자가 할 수 있는 동작이 하나도 없었다(막다른 화면).
 * 그래서 이 화면 하나에 넷을 둔다:
 * ① `h1` — 스크린리더가 이 화면의 정체를 먼저 읽는다.
 * ② 재시도 — 같은 경로로 다시 이동한다(서버 컴포넌트가 세션·조회를 다시 시도한다).
 * ③ 로그아웃 — 쿠키만 지운다(`fieldLogout`). Core 를 부르지 않아 Core 가 죽어 있는
 *    지금도 항상 동작한다.
 * ④ 조종기 브리지 진단 — Core 연결 여부와 무관하게 항상 렌더한다. 로그인 전에는
 *    이 진단 자체가 화면에 없어 FIELD-0b U9(djiBridge 키 기록)를 Core 없이 잴 수
 *    없었다.
 */
export function FieldBlocked({
  message,
  retryHref,
}: {
  message: string;
  /** "다시 시도"가 돌아갈 경로 — 지금 열려던 화면 그대로(FieldInlineLogin 의 `next`와 같은 값). */
  retryHref: string;
}) {
  return (
    <div className="field-controls flex flex-col gap-4 p-4">
      <h1 className="text-[17px] font-bold tracking-tight break-keep">현장 화면 연결 실패</h1>
      <div
        role="alert"
        className="flex flex-col gap-2 rounded-lg border border-crit/30 bg-crit-bg px-4 py-3 text-[13px] text-crit-ink"
      >
        <p className="font-semibold break-keep">{message}</p>
        <p className="break-keep text-crit-ink/80">
          토큰 문제가 아닙니다 — 다시 로그인해도 같은 결과입니다.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Link href={retryHref} className="btn btn-field">
          다시 시도
        </Link>
        <form action={fieldLogout}>
          <button type="submit" className="btn btn-field">
            로그아웃
          </button>
        </form>
      </div>
      <PilotBridgeProbe />
    </div>
  );
}
