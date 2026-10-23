import { headers } from "next/headers";
import Link from "next/link";

import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";
import { PATHNAME_HEADER } from "@/lib/core-api/session-cookie";

import { NormalShellTopBar } from "./ShellPathBoundary";
import { BackButton } from "./BackButton";
import { PageTitle } from "./PageTitle";
import { TopBarSearchTrigger } from "./TopBarSearchTrigger";
import { resolvePageTitle } from "./page-title";

function TopBarFrame({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <header className="print:hidden flex shrink-0 flex-wrap items-center gap-x-3.5 gap-y-2 border-b border-line bg-surface px-4 py-2.5 sm:px-5">
      <BackButton />
      <PageTitle fallback={title} />
      <span className="flex-1" />
      {children}
    </header>
  );
}

export async function TopBar() {
  const headerStore = await headers();
  const currentPathname = headerStore.get(PATHNAME_HEADER);
  const onLoginPage = currentPathname === "/login";
  const title = resolvePageTitle(currentPathname);

  // 신원·역할·로그아웃은 **레일 하단**(SidebarUserBlock)이 갖는다. 상단바에도 두면
  // 같은 정보가 한 화면에 두 벌 뜨고, 좁은 폭에서 제목을 밀어낸다(디자인 §0).
  //
  // 그런데도 여기서 whoAmI() 를 부르는 이유는 **세션 만료를 알리는 자리**가 상단바이기
  // 때문이다(아래 catch). 반환값은 쓰지 않는다 — 성공은 "만료가 아니다"라는 사실만
  // 뜻한다. 레일이 401 을 조용히 비우는 것과 역할을 나눈 결과다(SidebarUserBlock).
  try {
    await whoAmI();
  } catch (error) {
    // 로그인 화면 자체에서는 "다시 로그인하세요" 문구가 중복이니 숨긴다. 그 외
    // 화면에서는 조용히 숨기지 않는다 — proxy.ts 는 쿠키 "존재"만 보고 페이지 접근을
    // 허용하므로, 무효/만료 토큰을 쥔 사용자가 로그아웃 버튼도 없이 갇히는 데드락을
    // 막아야 한다(독립 재검토 1차 P1-A). /login 은 이제 세션 유무와 무관하게 항상
    // 도달 가능하다(proxy.ts 참조) — 그냥 링크로 충분하다.
    if (onLoginPage) return null;
    const expired = error instanceof MissingSessionError || (error instanceof CoreApiError && error.status === 401);
    const denied = error instanceof CoreApiError && error.status === 403;
    if (!expired && !denied) {
      return <TopBarFrame title={title}>
        <span role="status" className="rounded-md bg-sunk px-2.5 py-1 text-[13px] break-keep text-ink-2">
          서버 연결을 확인하지 못했습니다. 잠시 후 다시 시도하세요.
        </span>
      </TopBarFrame>;
    }
    // UX 목표 §5 "401 — 재로그인 유도(원래 화면으로 복귀 가능해야 함)" — x-pathname 이
    // 이미 손에 있으니 next 로 실어 재로그인 후 원래 화면에 복귀시킨다(독립 재검토 2차 P3-1).
    const loginHref = currentPathname
      ? `/login?next=${encodeURIComponent(currentPathname)}`
      : "/login";
    return (
      <TopBarFrame title={title}>
        <span className="rounded-md bg-high-bg px-2.5 py-1 text-[13px] break-keep text-high-ink">
          {denied ? "이 계정의 접근 권한을 확인하세요." : "세션이 만료되었습니다."}
        </span>
        <Link
          href={loginHref}
          className="tap-target flex min-h-11 items-center rounded-md border border-line-strong px-3 text-[13px] font-semibold hover:bg-sunk"
        >
          {denied ? "다른 계정으로 로그인" : "다시 로그인"}
        </Link>
      </TopBarFrame>
    );
  }

  // 세션이 살아 있는 정상 분기 — 사이드바가 숨는 lg 미만에서는 상단바가
  // 팔레트의 유일한 터치 입구다(⌘K 단축키가 없는 터치 기기를 위해).
  // 만료 분기에는 두지 않는다 — 검색 결과가 있어도 만료 세션에서는 열 수 없다.
  //
  // 집중 모드(자료 작업환경·디자인 예시)에서는 정상행을 그리지 않는다 —
  // 무대 위의 두 번째 타이틀바가 되기 때문이다. 팔레트 입구는 작업환경
  // 맥락막대의 검색 트리거가 맡는다. 인증 경보 분기는 그대로 둔다.
  return (
    <NormalShellTopBar>
    <TopBarFrame title={title}>
      <TopBarSearchTrigger />
    </TopBarFrame>
    </NormalShellTopBar>
  );
}
