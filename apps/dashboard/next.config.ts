import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
