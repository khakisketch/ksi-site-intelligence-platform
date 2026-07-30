import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { DesktopSidebar } from "@/components/nav/DesktopSidebar";
import { MobileBottomNav } from "@/components/nav/MobileBottomNav";

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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ko"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col lg:flex-row">
        <DesktopSidebar />
        <main className="min-h-full flex-1 pb-16 lg:pb-0">{children}</main>
        <MobileBottomNav />
      </body>
    </html>
  );
}
