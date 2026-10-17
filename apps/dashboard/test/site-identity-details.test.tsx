import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { duplicateSiteNames, SiteIdentityDetails } from "@/components/site/SiteIdentityDetails";

describe("same-name Site identification", () => {
  it("marks only real name collisions, independently of update time or ID suffix", () => {
    expect([...duplicateSiteNames([{ name: "동측" }, { name: "서측" }, { name: "동측" }])]).toEqual(["동측"]);
  });
  it("shows genuine registration time and keeps each full Site identity in a closed disclosure", () => {
    const html = renderToStaticMarkup(<SiteIdentityDetails site={{ siteId: "opaque-site-999", registeredAt: "2026-10-17T10:30:01Z" }} sameName />);
    expect(html).toContain("같은 이름의 현장");
    expect(html).toContain("2026. 10. 17.");
    expect(html).toContain("19:30:01");
    expect(html).toContain("<details><summary");
    expect(html).toContain("opaque-site-999</p></details>");
    expect(html).not.toContain("999회차");
    expect(html).not.toContain("open=");
  });
});
