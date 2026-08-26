import path from "node:path";
import type { NextConfig } from "next";

const extraAllowedDevOrigins = (process.env.KSI_DASHBOARD_ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const requestedDistDir = process.env.KSI_DASHBOARD_DIST_DIR?.trim();
if (requestedDistDir && (path.isAbsolute(requestedDistDir) || requestedDistDir.split(path.sep).includes(".."))) {
  throw new Error("KSI_DASHBOARD_DIST_DIR은 Dashboard 프로젝트 내부의 상대 경로여야 합니다.");
}

const nextConfig: NextConfig = {
  // Playwright 시각 회귀와 실제 개발 검토에서 Next dev 표시기가 모바일 하단 메뉴를
  // 덮지 않게 한다. 오류 overlay와 terminal 로그는 그대로 유지된다.
  devIndicators: false,
  // local OIDC stack은 기존 Dashboard dev 서버와 충돌하지 않도록 전용 distDir를 쓴다.
  // 배포는 env가 비어 있으므로 기존 .next 경로를 그대로 쓴다.
  ...(requestedDistDir ? { distDir: requestedDistDir } : {}),
  // VM image는 Next standalone output만 복사한다. 소스·dev 의존을 runtime image에
  // 남기지 않고 Auth.js/Core BFF를 같은 Node 프로세스로 실행한다.
  output: "standalone",
  // 홈 디렉터리에 무관한 package-lock.json 이 있어 Turbopack 이 workspace root 를
  // 잘못 추론한다 — apps/dashboard 를 명시적으로 고정한다.
  turbopack: {
    root: path.join(__dirname),
  },
  // **dev 전용.** Next 16 dev 서버는 기동 호스트(기본 localhost) 밖의 origin 에서
  // 온 dev 자산 요청을 403 으로 막는다. 그 결과 `127.0.0.1:<port>` 로 열면 HTML 은
  // 200 인데 클라이언트 청크만 403 이라 **화면은 멀쩡해 보이는데 아무 버튼도 눌리지
  // 않는다**(hydration 실패). 실제로 2026-08-05 렌더 확인이 이 함정에 빠졌고,
  // 콘솔을 열기 전까지 원인이 보이지 않았다.
  //
  // 프로덕션 빌드(`next build`/`start`)에는 영향이 없다 — 이 옵션은 dev 서버의
  // 자산 요청에만 적용된다.
  // Tailscale/LAN 주소는 머신마다 다르므로 저장소에 하드코딩하지 않고 개발 서버
  // 실행 시 쉼표 구분 환경변수로만 추가한다.
  allowedDevOrigins: ["127.0.0.1", ...extraAllowedDevOrigins],
};

export default nextConfig;
