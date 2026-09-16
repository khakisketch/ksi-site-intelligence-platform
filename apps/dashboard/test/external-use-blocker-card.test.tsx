// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { ExternalUseBlockerCard } from "@/components/external-results/ExternalUseBlockerCard";

afterEach(cleanup);

it("renders why, what to do, owner and a link to the target panel", () => {
  render(
    <ExternalUseBlockerCard
      reasons={["EVIDENCE_INDEPENDENCE_UNATTESTED"]}
      remediations={["ATTEST_INDEPENDENT_EVIDENCE"]}
    />,
  );
  expect(screen.getByRole("alert").textContent).toContain("체크포인트 증거에 독립성 확인이 없습니다");
  expect(screen.getByText("지금 할 일")).toBeTruthy();
  expect(screen.getByText(/독립 측량 확인/)).toBeTruthy();
  expect(screen.getByText("담당: 관리자")).toBeTruthy();
  expect(screen.getByRole("link", { name: "관련 화면으로 이동" }).getAttribute("href")).toBe("#external-evidence");
  expect(screen.getByText("EVIDENCE_INDEPENDENCE_UNATTESTED, ATTEST_INDEPENDENT_EVIDENCE")).toBeTruthy();
});

it("keeps raw codes visible for unknown reasons", () => {
  render(<ExternalUseBlockerCard reasons={["NEW_CODE"]} remediations={[]} />);
  expect(screen.getByRole("alert").textContent).toContain("판정이 막혔습니다");
  expect(screen.getByText("NEW_CODE")).toBeTruthy();
});
