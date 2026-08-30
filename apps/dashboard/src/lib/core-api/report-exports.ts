import "server-only";

import { coreFetch } from "./client";
import type {
  ReportExportCreateInput,
  ReportExportCreateResponse,
} from "./types";

/**
 * Browser-produced civil report export의 감사 스냅샷만 Core에 기록한다.
 *
 * PDF/CSV 바이트는 이 경로를 통과하지 않는다. Core는 현재의 불변 설계 대비
 * 리포트 두 건을 다시 확인해 그 스냅샷의 digest만 원장에 남긴다.
 */
export async function recordReportExport(
  siteId: string,
  input: ReportExportCreateInput,
): Promise<ReportExportCreateResponse> {
  return coreFetch<ReportExportCreateResponse>(
    `/v1/sites/${encodeURIComponent(siteId)}/report-exports`,
    { method: "POST", body: input },
  );
}
