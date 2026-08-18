import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";

import { DesktopSidebar } from "@/components/nav/DesktopSidebar";
import { isChromelessPath } from "@/components/nav/chromeless-path";
import { getNavCounts } from "@/components/nav/nav-counts";
import { MobileBottomNav } from "@/components/nav/MobileBottomNav";
import { SidebarUserBlock } from "@/components/nav/SidebarUserBlock";
import { TopBar } from "@/components/nav/TopBar";
import { resolvePageTitle } from "@/components/nav/page-title";
import { CommandPalette } from "@/components/console/CommandPalette";
import { buildPaletteItems } from "@/components/console/palette-source";
import { PATHNAME_HEADER } from "@/lib/core-api/session-cookie";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "KSI Site Intelligence",
  description: "현장 순찰·이벤트 트리아지·임무 관리 대시보드",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const headerStore = await headers();
  // 셸을 벗는 화면(/login · /field/*)에서는 사이드바 자체가 없다 — 여기서 집계를
  // 부르면 아무도 보지 않는 배지를 위해 매 요청 왕복만 늘린다(로그인 화면에서는
  // 세션조차 없어 401 왕복이 된다).
  const chromeless = isChromelessPath(headerStore.get(PATHNAME_HEADER));
  const currentPageTitle = resolvePageTitle(headerStore.get(PATHNAME_HEADER)) || "KSI Site Intelligence";
  // 셸을 벗는 화면에서는 팔레트도 없다 — /field 는 조종기 화면이라 ⌘K 가 의미 없고,
  // /login 은 아직 세션이 없어 현장 목록을 부르면 401 왕복만 는다.
  const [navCounts, paletteItems] = chromeless
    ? [undefined, []]
    : await Promise.all([getNavCounts(), buildPaletteItems()]);

  return (
    <html
      lang="ko"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      {/* 앱 셸 — 시안(ink-mono)의 .shell 을 그대로 옮긴다.
          lg 이상에서 뷰포트 높이에 고정되고 **본문만 스크롤한다**. 이게 문서와 앱을
          가르는 가장 큰 한 가지다: 레일과 상단바가 스크롤에 딸려 올라가지 않으면
          화면은 "열어 둔 도구"로 읽히고, 같이 밀려 올라가면 "긴 페이지"로 읽힌다.
          폭은 시안대로 1280+ 232px · 1024~1279 176px(Console v2 §0).
          lg 미만에서는 하단 탭 + 일반 문서 흐름으로 떨어진다(PRD §7.1).

          /login 과 /field/* 는 셸을 통째로 벗는다(isChromelessPath — 판정 근거는 그
          모듈 주석). 이 그리드는 첫 트랙이 사이드바라는 전제 위에 있는데, 셸을 벗는
          화면에서는 DesktopSidebar 와 MobileBottomNav 가 **둘 다** null 을 반환해 남는
          자식이 본문 wrapper 하나뿐이다. 그러면 그 하나가 176px 트랙으로 들어가 로그인
          카드가 레일 폭으로 눌린다. 자식 수에 의존하는 레이아웃이라 "사이드바가 없는
          화면"을 예외로 처리하지 않으면 조용히 깨진다.

          TopBar 도 여기서 끊는다. 예전에는 TopBar 가 스스로 /login 을 판별했는데 그
          판별은 whoAmI 가 **실패했을 때만** 걸려서, 유효 세션을 쥔 채 /login 을 열면
          앱 상단바가 로그인 카드 위에 남았다. /field 에서는 그게 더 나쁘다 — 현장
          화면은 자기 헤더(누가 로그인했나 + 로그아웃)를 갖고 있어 상단바가 그대로
          남으면 헤더가 두 겹이 되고, 세로가 짧은 조종기 화면에서 본문이 그만큼 밀린다. */}
      <body
        className={
          chromeless
            ? "min-h-full"
            : "min-h-full lg:grid lg:h-screen lg:grid-cols-[176px_1fr] lg:overflow-hidden xl:grid-cols-[232px_1fr]"
        }
      >
        {!chromeless && (
          <a href="#main-content" className="skip-link">
            본문으로 건너뛰기
          </a>
        )}
        <DesktopSidebar counts={navCounts} userBlock={!chromeless && <SidebarUserBlock />} />
        <div className="flex min-h-full flex-col lg:min-h-0 lg:overflow-hidden">
          {!chromeless && <TopBar />}
          <main
            id="main-content"
            tabIndex={-1}
            className="flex-1 pb-16 lg:min-h-0 lg:overflow-y-auto lg:pb-0"
          >
            {!chromeless && <h1 className="sr-only">{currentPageTitle}</h1>}
            {children}
          </main>
        </div>
        <MobileBottomNav />
        {!chromeless && <CommandPalette items={paletteItems} />}
      </body>
    </html>
  );
}
