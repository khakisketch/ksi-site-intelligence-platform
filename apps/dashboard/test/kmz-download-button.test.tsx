// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { KmzDownloadButton } from "@/components/missions/KmzDownloadButton";

afterEach(cleanup);

describe("KmzDownloadButton", () => {
  it("never presents an unavailable KMZ as a clickable control", () => {
    render(<KmzDownloadButton missionId="mission-1" hasKmz={false} />);
    // A real button must not exist at all in this state — only an explicit,
    // unambiguously non-interactive notice.
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("KMZ 다운로드 불가")).toBeTruthy();
    expect(screen.getByText("이 임무는 계약만 발급되어 내려받을 KMZ 파일이 없습니다.")).toBeTruthy();
  });

  it("presents a real clickable button when a KMZ exists", () => {
    render(<KmzDownloadButton missionId="mission-1" hasKmz={true} />);
    const button = screen.getByRole("button", { name: "KMZ 다운로드" });
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });
});
