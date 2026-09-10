/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/field/ExternalSanitizedOrthophoto", () => ({
  ExternalSanitizedOrthophoto: ({ workOrderId, sanitizedDisplayRef }: { workOrderId: string; sanitizedDisplayRef: string }) => <p data-testid="safe-derivative">{workOrderId}:{sanitizedDisplayRef}</p>,
}));

import { ExternalReportSafeDerivativeComparison } from "@/app/sites/[siteId]/observations/[reportRef]/ExternalReportSafeDerivativeComparison";

const digest = `sha256:${"a".repeat(64)}`;
const subject = (role: "baseline" | "current") => ({
  role,
  workOrderId: `${role}-order`,
  submissionRef: `ers-v1-${role}`,
  revision: 1,
  sanitizedDisplayRef: `sda-v1-${role}`,
  receiptDigest: digest,
  capturedFrom: "2026-09-01T00:00:00Z",
  capturedTo: "2026-09-01T00:10:00Z",
});

afterEach(cleanup);

describe("exact report safe derivative comparison", () => {
  it("opens only the paired, re-bound display derivatives after an explicit choice", () => {
    render(<ExternalReportSafeDerivativeComparison pair={{ state: "READY", baseline: subject("baseline"), current: subject("current") }} />);
    expect(screen.queryAllByTestId("safe-derivative")).toHaveLength(0);
    expect(screen.getByText(/열지도/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "기준·현재 정제 정사영상 보기" }));

    expect(screen.getAllByTestId("safe-derivative").map((item) => item.textContent)).toEqual([
      "baseline-order:sda-v1-baseline",
      "current-order:sda-v1-current",
    ]);
  });

  it("does not create a substitute display when exact retained bindings are unavailable", () => {
    render(<ExternalReportSafeDerivativeComparison pair={{ state: "UNAVAILABLE", reason: "결속을 확인하지 못했습니다." }} />);
    expect(screen.getByRole("status").textContent).toMatch(/원본 파일이나 추정 표시/);
    expect(screen.queryByRole("button", { name: /정제 정사영상 보기/ })).toBeNull();
  });
});
