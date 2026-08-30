import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  formatProcessingResourceBytes,
  formatProcessingResourceMegapixels,
  processingResourceLimitNextAction,
  resolveCurrentProcessingResourcePolicy,
} from "@/lib/processing-resource-policy";
import type { ProcessingResourcePolicyListView } from "@/lib/core-api/types";

const response: ProcessingResourcePolicyListView = {
  currentPolicyId: "ksi-civil-pilot-r1",
  policies: [
    {
      resourcePolicyId: "ksi-civil-pilot-r1",
      policyVersion: "v1",
      maxSourceMediaFiles: 5_000,
      maxSourceMediaFileBytes: 1_073_741_824,
      maxSourceBundleBytes: 1_099_511_627_776,
      maxTotalMegapixels: 150_000,
      maxActiveProcessingJobsPerOrganization: 20,
      resourcePolicyDigest: "sha256:" + "a".repeat(64),
    },
  ],
};

describe("Processing Resource Policy 표시/발급 경계", () => {
  it("Core가 지정한 currentPolicyId만 선택한다", () => {
    expect(resolveCurrentProcessingResourcePolicy(response)).toEqual({
      kind: "ready",
      policy: response.policies[0],
    });
  });

  it("current policy가 목록에 없으면 임의 첫 정책으로 넘어가지 않고 fail-closed한다", () => {
    expect(
      resolveCurrentProcessingResourcePolicy({ ...response, currentPolicyId: "unknown-policy" }),
    ).toEqual({ kind: "unavailable", reason: "CURRENT_POLICY_UNKNOWN" });
  });

  it("old/forged response의 currentPolicyId 누락도 fail-closed한다", () => {
    expect(
      resolveCurrentProcessingResourcePolicy({ policies: response.policies } as ProcessingResourcePolicyListView),
    ).toEqual({ kind: "unavailable", reason: "CURRENT_POLICY_UNDECLARED" });
  });

  it("용량과 화소는 표시용으로만 사람이 읽을 단위로 바꾼다", () => {
    expect(formatProcessingResourceBytes(1_073_741_824)).toBe("1 GiB");
    expect(formatProcessingResourceBytes(1_099_511_627_776)).toBe("1 TiB");
    expect(formatProcessingResourceMegapixels(150_000)).toBe("150,000 MP");
  });

  it.each([
    ["SOURCE_MEDIA_FILES_LIMIT_EXCEEDED", "촬영 회차 또는 구역으로 나눠"],
    ["SOURCE_MEDIA_FILE_BYTES_LIMIT_EXCEEDED", "카메라 출력 설정"],
    ["SOURCE_BUNDLE_BYTES_LIMIT_EXCEEDED", "촬영 회차 또는 구역을 나눠"],
    ["TOTAL_MEGAPIXELS_LIMIT_EXCEEDED", "촬영 회차 또는 구역을 나눠"],
    ["ACTIVE_PROCESSING_JOBS_PER_ORGANIZATION_LIMIT_EXCEEDED", "진행 중인 작업이 끝난 뒤"],
  ])("한도 하위 사유 %s에 다음 행동을 준다", (reasonCode, expected) => {
    expect(processingResourceLimitNextAction(reasonCode)).toContain(expected);
  });

  it("재구성 POST 본문에는 서버 소유 정책/한도/override를 넣지 않는다", () => {
    const source = readFileSync(
      join(process.cwd(), "src/components/missions/SourceUploadPanel.tsx"),
      "utf8",
    );
    const requestSlice = source.slice(source.indexOf("body: JSON.stringify(RECONSTRUCTION_SPEC)"), source.indexOf("});", source.indexOf("body: JSON.stringify(RECONSTRUCTION_SPEC)")));
    expect(requestSlice).not.toMatch(/resourcePolicy|resourceLimit|override/i);
  });
});
