import type { Metadata } from "next";
import { Suspense } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";

import { AccountDisplayBoundary } from "@/components/nav/AccountDisplayBoundary";
import { DesktopSidebar } from "@/components/nav/DesktopSidebar";
import { isChromelessPath } from "@/components/nav/chromeless-path";
import { isViewerPath } from "@/components/nav/viewer-path";
import { ConnectivityNotice } from "@/components/nav/ConnectivityNotice";
import { SiteListRefreshNotice } from "@/components/nav/SiteListRefreshNotice";
import { SiteListProvider } from "@/components/nav/SiteListContext";
import type { SidebarSite } from "@/components/nav/site-context";
import { getNavCounts } from "@/components/nav/nav-counts";
import { readRootShellSnapshot } from "@/components/nav/root-shell-snapshot";
import { MobileBottomNav } from "@/components/nav/MobileBottomNav";
import { MainPageTitle } from "@/components/nav/PageTitle";
import { RouteFocusManager } from "@/components/nav/RouteFocusManager";
import { ShellLayoutMode, ShellMain, ShellOnly, ShellViewport } from "@/components/nav/ShellPathBoundary";
import { RailAccount } from "@/components/nav/RailAccount";
import { TopBar } from "@/components/nav/TopBar";
import { resolvePageTitle } from "@/components/nav/page-title";
import { CommandPalette } from "@/components/console/CommandPalette";
import { SessionRefresh } from "@/components/auth/SessionRefresh";
import { ToastProvider } from "@/components/ui/ToastProvider";
import { buildPaletteItems } from "@/components/console/palette-source";
import { getDashboardAuthRuntime } from "@/lib/auth/runtime";
import { PATHNAME_HEADER, SEARCH_HEADER } from "@/lib/core-api/session-cookie";

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
  description: "현장 변화를 근거와 함께 읽고 다음 결정을 연결하는 Operations Console",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const headerStore = await headers();
  const authRuntime = getDashboardAuthRuntime();
  // 셸을 벗는 화면(/login)에서는 사이드바 자체가 없다 — 여기서 집계를
  // 부르면 아무도 보지 않는 배지를 위해 매 요청 왕복만 늘린다(로그인 화면에서는
  // 세션조차 없어 401 왕복이 된다).
  const chromeless = isChromelessPath(headerStore.get(PATHNAME_HEADER));
  const currentPathname = headerStore.get(PATHNAME_HEADER);
  const viewerShell = !chromeless && isViewerPath(currentPathname, headerStore.get(SEARCH_HEADER));
  const currentPageTitle = resolvePageTitle(currentPathname, new URLSearchParams(headerStore.get(SEARCH_HEADER) ?? "")) || "KSI Site Intelligence";
  // 셸을 벗는 로그인 화면에는 세션이 없어 현장 목록을 부르면 401 왕복만 는다.
  // Bind shell identity, site menu, counts and palette to one resolved token.
  // Separate page RSCs still have their own snapshot and authorization checks.
  const shellSnapshot = chromeless ? null : await readRootShellSnapshot();
  const shellFingerprint = shellSnapshot?.fingerprint ?? null;
  const [navCounts, paletteItems] = chromeless
    ? [undefined, []]
    : await Promise.all([getNavCounts(shellSnapshot?.sites ?? null), buildPaletteItems(shellSnapshot?.sites ?? null)]);
  const sidebarSites: SidebarSite[] = (shellSnapshot?.sites ?? [])
    .map(({ siteId, name, status }) => ({ siteId, name, status }));

  return (
    <html
      lang="ko"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      // 브라우저 확장(예: 한컴 확장)이 <html>에 속성을 끼워 넣어 hydration이
      // 깨지는 경우를 무시한다. 앱이 그리는 요소의 불일치는 그대로 보고된다.
      suppressHydrationWarning
    >
      {/* 앱 셸 — 시안(ink-mono)의 .shell 을 그대로 옮긴다.
          lg 이상에서 뷰포트 높이에 고정되고 **본문만 스크롤한다**. 이게 문서와 앱을
          가르는 가장 큰 한 가지다: 레일과 상단바가 스크롤에 딸려 올라가지 않으면
          화면은 "열어 둔 도구"로 읽히고, 같이 밀려 올라가면 "긴 페이지"로 읽힌다.
          구조는 헤더 한 줄 + (레일 188px | 본문) 한 줄이며 레일은 56px 로 접을 수 있다(ADR-KSI-043).
          lg 미만에서는 하단 탭 + 일반 문서 흐름으로 떨어진다(PRD §7.1).

          /login 은 셸을 통째로 벗는다(isChromelessPath — 판정 근거는 그
          모듈 주석). 이 그리드는 첫 트랙이 사이드바라는 전제 위에 있는데, 셸을 벗는
          화면에서는 DesktopSidebar 와 MobileBottomNav 가 **둘 다** null 을 반환해 남는
          자식이 본문 wrapper 하나뿐이다. 그러면 그 하나가 레일 폭 트랙으로 들어가 로그인
          카드가 레일 폭으로 눌린다. 자식 수에 의존하는 레이아웃이라 "사이드바가 없는
          화면"을 예외로 처리하지 않으면 조용히 깨진다.

          TopBar 도 여기서 끊는다. 예전에는 TopBar 가 스스로 /login 을 판별했는데 그
          판별은 whoAmI 가 **실패했을 때만** 걸려서, 유효 세션을 쥔 채 /login 을 열면
          앱 상단바가 로그인 카드 위에 남았다. */}
      <body
        className={
          chromeless
            ? "min-h-full"
            : `min-h-full md:grid md:h-screen md:grid-cols-[56px_1fr] md:grid-rows-[auto_minmax(0,1fr)] md:overflow-hidden lg:grid-cols-[188px_1fr]${viewerShell ? " viewer-shell" : ""}`
        }
      >
        <AccountDisplayBoundary fingerprint={shellFingerprint} bypass={chromeless} ownsFreshLoginMarker>
        <SiteListProvider sites={sidebarSites} fingerprint={shellFingerprint}>
          <ShellLayoutMode />
          {!chromeless && (
            <ShellOnly>
              <a href="#main-content" className="skip-link">
                본문으로 건너뛰기
              </a>
            </ShellOnly>
          )}
          {!chromeless && (
            <ShellOnly>
              <TopBar />
            </ShellOnly>
          )}
          <DesktopSidebar
            counts={navCounts}
            account={chromeless ? null : <Suspense fallback={null}><RailAccount /></Suspense>}
          />
          <ShellViewport>
            <ShellMain>
              {!chromeless && <MainPageTitle fallback={currentPageTitle} />}
              {!chromeless && <ConnectivityNotice />}
              <SiteListRefreshNotice />
              <ToastProvider>{children}</ToastProvider>
            </ShellMain>
          </ShellViewport>
          <MobileBottomNav />
          {!chromeless && <RouteFocusManager />}
          {!chromeless && <CommandPalette items={paletteItems} />}
          {authRuntime.mode !== "OPAQUE" && <SessionRefresh />}
        </SiteListProvider>
        </AccountDisplayBoundary>
      </body>
    </html>
  );
}
