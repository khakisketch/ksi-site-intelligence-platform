/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { MaskedAnalysisPanel } from "@/app/sites/[siteId]/analysis/MaskedAnalysisPanel";
import { parseMaskedCalculationDetail } from "@/lib/core-api/masked-analysis";
import raw from "./masked-browser-core-detail.json";

afterEach(cleanup);

it("retains positive sub-square-metre areas from the actual padded-window report", () => {
  const detail = parseMaskedCalculationDetail(raw, {
    siteId: raw.siteId, workAreaId: raw.workAreaId, requestId: raw.requestId,
  });
  render(<MaskedAnalysisPanel siteId={raw.siteId} workAreaId={raw.workAreaId}
    workAreaName="합성 구역" canRequest={false} maskBudgetBytes={null}
    sourceCalculationIdentityDigest={detail.admission!.sourceCalculationIdentityDigest}
    initialChild={null} initialCalculation={detail} />);
  expect(screen.getByText("4 · 0.04 m²")).toBeTruthy();
  expect(screen.getByText("3 · 0.03 m²")).toBeTruthy();
  expect(screen.queryByText("4 · 0 m²")).toBeNull();
});
