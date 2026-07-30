import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 홈 디렉터리에 무관한 package-lock.json 이 있어 Turbopack 이 workspace root 를
  // 잘못 추론한다 — apps/dashboard 를 명시적으로 고정한다.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
