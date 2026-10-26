import { describe, expect, it } from "vitest";

import { isViewerPath } from "@/components/nav/viewer-path";

describe("viewer-first path boundary", () => {
  it("treats site space and materials as viewer surfaces", () => {
    expect(isViewerPath("/sites/floreat")).toBe(true);
    expect(isViewerPath("/sites/floreat/")).toBe(true);
    expect(isViewerPath("/sites/floreat?section=workspace")).toBe(true);
    expect(isViewerPath("/sites/floreat?mode=compare")).toBe(true);
    expect(isViewerPath("/sites/floreat?mode=explore&workAreaId=a1")).toBe(true);
    expect(isViewerPath("/sites/floreat/spatial-assets")).toBe(true);
    expect(isViewerPath("/sites/floreat/spatial-assets/")).toBe(true);
    expect(isViewerPath("/sites/floreat/spatial-assets?assetRef=x&info=1")).toBe(true);
    expect(isViewerPath("/sites/floreat%20north")).toBe(true);
  });

  it("keeps management and review dense", () => {
    expect(isViewerPath("/sites/floreat?section=work-orders")).toBe(false);
    expect(isViewerPath("/sites/floreat?section=manage")).toBe(false);
    expect(isViewerPath("/sites/floreat?section=results")).toBe(false);
    expect(isViewerPath("/sites/floreat?section=materials")).toBe(false);
    expect(isViewerPath("/sites/floreat?mode=results")).toBe(false);
    expect(isViewerPath("/sites/floreat/analysis")).toBe(false);
    expect(isViewerPath("/sites/floreat/spatial-data-requests")).toBe(false);
    expect(isViewerPath("/sites/floreat/observations")).toBe(false);
    expect(isViewerPath("/sites/floreat/work-areas")).toBe(false);
  });

  it("does not turn global or unregistered-site screens into viewers", () => {
    expect(isViewerPath("/")).toBe(false);
    expect(isViewerPath("/sites")).toBe(false);
    expect(isViewerPath("/sites/new")).toBe(false);
    expect(isViewerPath("/field")).toBe(false);
    expect(isViewerPath("/login")).toBe(false);
    expect(isViewerPath(null)).toBe(false);
  });
});
