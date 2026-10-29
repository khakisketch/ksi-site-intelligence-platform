import { expect, it } from "vitest";
import { SITE_DETAIL_DOCUMENT_TITLE } from "@/lib/site-detail-title";
it("현장 상세 문서 제목은 현장 식별자가 없는 중립 제목이다", () => {
  expect(SITE_DETAIL_DOCUMENT_TITLE).toBe("현장 상세 · KSI");
});
