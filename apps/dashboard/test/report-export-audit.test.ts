import { afterEach, describe, expect, it, vi } from "vitest";

import {
  exportIdForAttempt,
  recordBeforeBrowserExport,
  requestReportExportAudit,
} from "@/components/reports/ReportExportControls";
import type { ReportExportCreateResponse } from "@/lib/core-api/types";

function recorded(overrides: Partial<ReportExportCreateResponse> = {}): ReportExportCreateResponse {
  return {
    verdict: "RECORDED",
    exportId: "export-1",
    recordedAt: "2026-08-30T02:00:00Z",
    snapshotDigest: `sha256:${"a".repeat(64)}`,
    contentProducedByServer: false,
    detail: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("report export audit before browser output", () => {
  it.each(["PDF", "CSV"] as const)("%s 출력은 감사 기록 뒤에만 시작한다", async (format) => {
    const sequence: string[] = [];

    await recordBeforeBrowserExport(
      async () => {
        sequence.push("audit");
        return recorded();
      },
      () => sequence.push(format === "PDF" ? "print" : "blob"),
    );

    expect(sequence).toEqual(["audit", format === "PDF" ? "print" : "blob"]);
  });

  it("감사 요청 실패면 인쇄/Blob 출력을 시작하지 않는다", async () => {
    const produce = vi.fn();

    await expect(
      recordBeforeBrowserExport(async () => {
        throw new Error("Core unavailable");
      }, produce),
    ).rejects.toThrow("Core unavailable");

    expect(produce).not.toHaveBeenCalled();
  });

  it("서버가 파일을 만들었다는 응답이나 미완전한 snapshot은 출력하지 않는다", async () => {
    const produce = vi.fn();

    await expect(
      recordBeforeBrowserExport(async () => recorded({ contentProducedByServer: true }), produce),
    ).rejects.toThrow("내보내기를 시작하지 않았습니다");

    expect(produce).not.toHaveBeenCalled();
  });

  it("BFF로 site와 불변 report ID만 보낸다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(recorded()), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await requestReportExportAudit("site / 1", {
      exportId: "export-1",
      exportFormat: "CSV",
      baselineDesignConformanceId: "baseline-1",
      latestDesignConformanceId: "latest-1",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/sites/site%20%2F%201/report-exports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exportId: "export-1",
        exportFormat: "CSV",
        baselineDesignConformanceId: "baseline-1",
        latestDesignConformanceId: "latest-1",
      }),
    });
  });

  it("응답 유실 뒤 같은 형식 재시도는 보존한 action ID를 쓴다", () => {
    expect(exportIdForAttempt("export-retry")).toBe("export-retry");
  });
});
