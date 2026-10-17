import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SyntheticDemoNotice } from "@/components/console/SyntheticDemoNotice";

describe("explicit local synthetic context", () => {
  it("clearly distinguishes synthetic measurement values from a customer Site", () => {
    const html = renderToStaticMarkup(<SyntheticDemoNotice deploymentProfile="LOCAL" marker="1" />);
    expect(html).toContain('aria-label="합성 자료 시연 안내"');
    expect(html).toContain("실제 현장 측정값이 아닙니다");
    expect(html).not.toMatch(/검증 완료|정확도 인증|href=|<h[12]/);
  });

  it.each([undefined, "", "true", "0", " 1 "])("does not infer a synthetic dataset from a loose marker %s", (marker) => {
    expect(renderToStaticMarkup(<SyntheticDemoNotice deploymentProfile="LOCAL" marker={marker} />)).toBe("");
  });

  it.each(["EXTERNAL_VM", "PRODUCTION", "", "unknown"])("never marks an external deployment as this local rehearsal (%s)", (deploymentProfile) => {
    expect(renderToStaticMarkup(<SyntheticDemoNotice deploymentProfile={deploymentProfile} marker="1" />)).toBe("");
  });
});
