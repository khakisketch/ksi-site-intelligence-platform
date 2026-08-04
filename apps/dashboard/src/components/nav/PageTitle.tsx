"use client";

import { usePathname } from "next/navigation";

import { resolvePageTitle } from "./page-title";

// 제목만 클라이언트에서 계산한다 — proxy.ts 가 심는 x-pathname 헤더는 **하드 로드에서만**
// 갱신된다. App Router 의 layout 은 클라이언트 네비게이션 사이에 보존되므로(의도된 동작),
// 서버 헤더로 제목을 받으면 링크를 눌러 이동했을 때 topbar 가 이전 화면 이름에 머문다
// (2026-08-04 렌더 확인에서 실제 재현: 현장 등록 → 현장 상세 이동 후에도 "현장 등록").
//
// TopBar 의 나머지(세션·역할·날짜)는 서버 컴포넌트로 남는다 — 저 데이터는 화면 전환마다
// 바뀌지 않고, 클라이언트로 내리면 principal 을 브라우저 번들에 실어야 한다.
export function PageTitle({ fallback }: { fallback: string }) {
  const pathname = usePathname();
  // usePathname 은 SSR 에서도 값을 준다 — fallback 은 그 값이 아직 없는 극히 초기 렌더용이다.
  return (
    <h1 className="text-[17px] font-bold tracking-tight break-keep">
      {pathname ? resolvePageTitle(pathname) : fallback}
    </h1>
  );
}
