import { renderToStaticMarkup } from "react-dom/server";

import { describe, expect, it } from "vitest";

import { TopUnattendedHeadline } from "@/app/TopUnattendedHeadline";

describe("TopUnattendedHeadline", () => {
  it("names the assigned-work inbox separately from an observation record", () => {
    expect(renderToStaticMarkup(<TopUnattendedHeadline pendingCount={null} />)).toBe(
      "받은 작업함 확인 불가",
    );
    expect(renderToStaticMarkup(<TopUnattendedHeadline pendingCount={0} />)).toBe("받은 작업함");
    expect(renderToStaticMarkup(<TopUnattendedHeadline pendingCount={2} />)).toBe(
      "받은 작업함 2건",
    );
  });
});
