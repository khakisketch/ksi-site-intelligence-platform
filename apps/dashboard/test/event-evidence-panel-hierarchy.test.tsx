// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { EvidencePanel } from "@/app/events/[eventKey]/EvidencePanel";
import type { EvidenceSummary } from "@/lib/core-api/types";

afterEach(cleanup);

function evidence(overrides: Partial<EvidenceSummary> = {}): EvidenceSummary {
  return {
    artifactId: "20260917013045-photo.jpg",
    contentType: "image/jpeg",
    registeredAt: "2026-09-17T01:30:45Z",
    registeredBy: "operator-a",
    deviceBound: true,
    deviceAttested: true,
    attestationKeyId: "key-1",
    tombstonedAt: null,
    tombstoneReason: null,
    ...overrides,
  };
}

describe("EvidencePanel row hierarchy", () => {
  it("leads each row with a human evidence kind, not the raw artifact id", () => {
    render(<EvidencePanel eventKey="event-1" evidence={[evidence()]} canUpload={false} />);
    const row = screen.getByTestId("evidence-row");
    const heading = row.querySelector("[data-evidence-heading]");
    expect(heading?.textContent).toBe("사진 증거");
  });

  it("moves the artifact id and raw content type into a muted expert subline", () => {
    render(<EvidencePanel eventKey="event-1" evidence={[evidence()]} canUpload={false} />);
    const row = screen.getByTestId("evidence-row");
    const subline = row.querySelector("[data-evidence-subline]");
    expect(subline?.textContent).toContain("20260917013045-photo.jpg");
    expect(subline?.textContent).toContain("image/jpeg");
  });

  it("labels a video artifact distinctly from a photo", () => {
    render(
      <EvidencePanel
        eventKey="event-1"
        evidence={[evidence({ artifactId: "clip.mp4", contentType: "video/mp4" })]}
        canUpload={false}
      />,
    );
    expect(screen.getByText("동영상 증거")).toBeTruthy();
  });
});
