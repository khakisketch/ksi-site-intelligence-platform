import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";

import { DesktopSidebar } from "@/components/nav/DesktopSidebar";
import { getNavCounts } from "@/components/nav/nav-counts";
import { MobileBottomNav } from "@/components/nav/MobileBottomNav";
import { TopBar } from "@/components/nav/TopBar";
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
  // 로그인 화면에는 세션이 없다 — 여기서 집계를 부르면 매번 401 왕복만 늘린다.
  const onLoginPage = headerStore.get(PATHNAME_HEADER) === "/login";
  const navCounts = onLoginPage ? undefined : await getNavCounts();

  return (
    <html
      lang="ko"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      {/* 앱 셸 — 시안(ink-mono)의 .shell 을 그대로 옮긴다.
          lg 이상에서 뷰포트 높이에 고정되고 **본문만 스크롤한다**. 이게 문서와 앱을
          가르는 가장 큰 한 가지다: 레일과 상단바가 스크롤에 딸려 올라가지 않으면
          화면은 "열어 둔 도구"로 읽히고, 같이 밀려 올라가면 "긴 페이지"로 읽힌다.
          폭은 시안대로 1280+ 216px · 1024~1279 176px.
          lg 미만에서는 하단 탭 + 일반 문서 흐름으로 떨어진다(PRD §7.1).

          /login 은 셸을 통째로 벗는다. 이 그리드는 첫 트랙이 사이드바라는 전제 위에
          있는데, 로그인 화면에서는 DesktopSidebar 와 MobileBottomNav 가 **둘 다** null 을
          반환해 남는 자식이 본문 wrapper 하나뿐이다. 그러면 그 하나가 176px 트랙으로
          들어가 로그인 카드가 레일 폭으로 눌린다. 자식 수에 의존하는 레이아웃이라
          "사이드바가 없는 화면"을 예외로 처리하지 않으면 조용히 깨진다. */}
      <body
        className={
          onLoginPage
            ? "min-h-full"
            : "min-h-full lg:grid lg:h-screen lg:grid-cols-[176px_1fr] lg:overflow-hidden xl:grid-cols-[216px_1fr]"
        }
      >
        <DesktopSidebar counts={navCounts} />
        <div className="flex min-h-full flex-col lg:min-h-0 lg:overflow-hidden">
          <TopBar />
          <main className="flex-1 pb-16 lg:min-h-0 lg:overflow-y-auto lg:pb-0">{children}</main>
        </div>
        <MobileBottomNav />
      </body>
    </html>
  );
}
