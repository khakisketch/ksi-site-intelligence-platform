import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// 이 프로젝트의 프런트 테스트는 **순수 로직만** 본다 — 렌더링·동선 검증은
// CLAUDE.md UI 절의 렌더 확인(390/768/1440 실캡처)과 /ui-audit 이 맡는다.
// 서버 컴포넌트를 jsdom 으로 흉내내기 시작하면 그 흉내가 진짜 화면과 어긋나는
// 순간 초록불이 거짓말이 되고, 이 제품에서 가장 나쁜 거짓말이 그거다.
//
// 그래서 environment 는 node 고 jsdom 을 넣지 않았다. 대상은 안전·보안 판정이
// 걸린 순수 함수들이다 — CSRF 판정 · AOI 볼록성 · 트리아지 정의 · 에러코드 추출.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // `server-only` 는 클라이언트 번들에 섞이면 빌드를 깨뜨리라고 존재하는
      // 패키지다. Node 테스트 러너에는 그 구분이 없으므로 빈 모듈로 바꾼다 —
      // 이 alias 는 vitest 에만 적용되고 next build 의 경계 검사에는 영향이 없다.
      "server-only": fileURLToPath(new URL("./test/stubs/server-only.ts", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});
