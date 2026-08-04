// `server-only` 대체 모듈(vitest 전용 — vitest.config.ts 의 alias 참조).
// 진짜 패키지는 클라이언트 번들에 들어가면 빌드를 실패시키는 게 유일한 일이다.
// Node 테스트에는 그 경계가 없으므로 아무것도 하지 않는다.
export {};
