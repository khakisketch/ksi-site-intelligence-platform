import { describe, expect, it } from "vitest";

import {
  duplicateSealedTargetKeys,
  sealedTargetSubjectKey,
} from "@/app/field/registration-language";

const refA = `ers-v1-${"a".repeat(64)}`;
const refB = `ers-v1-${"b".repeat(64)}`;

function dsmTarget(submissionRef: string, fileName = "current.tif", revision = 1) {
  return {
    submissionRef,
    revision,
    artifacts: [{ artifactId: "dsm", kind: "dsm", fileName }],
  };
}

describe("duplicateSealedTargetKeys", () => {
  it("returns no keys when only one sealed target is listed", () => {
    expect(duplicateSealedTargetKeys([dsmTarget(refA)])).toEqual(new Set());
  });

  it("marks both targets when different submission refs share revision and file names", () => {
    expect(duplicateSealedTargetKeys([dsmTarget(refA), dsmTarget(refB)])).toEqual(
      new Set([`${refA}:1`, `${refB}:1`]),
    );
  });

  it("keeps distinct revisions, file names, and artifact kinds merge-free without ids", () => {
    expect(
      duplicateSealedTargetKeys([dsmTarget(refA, "current.tif", 1), dsmTarget(refB, "current.tif", 2)]),
    ).toEqual(new Set());
    expect(
      duplicateSealedTargetKeys([dsmTarget(refA, "current.tif"), dsmTarget(refB, "next.tif")]),
    ).toEqual(new Set());
    expect(
      duplicateSealedTargetKeys([
        dsmTarget(refA),
        { submissionRef: refB, revision: 1, artifacts: [{ artifactId: "ortho", kind: "ortho", fileName: "current.tif" }] },
      ]),
    ).toEqual(new Set());
  });

  it("marks only the colliding pair when a third target is distinct", () => {
    expect(
      duplicateSealedTargetKeys([dsmTarget(refA), dsmTarget(refB), dsmTarget(refA, "other.tif", 2)]),
    ).toEqual(new Set([`${refA}:1`, `${refB}:1`]));
  });

  it("builds the exact retained subject key without inventing identifiers", () => {
    expect(sealedTargetSubjectKey({ submissionRef: refA, revision: 2 })).toBe(`${refA}:2`);
  });
});

describe("V3 missing-info display readers", () => {
  it("formats the publisher calendar date without timezone conversion", async () => {
    const { formatPublisherCalendarDate } = await import("@/app/field/registration-language");
    expect(formatPublisherCalendarDate("2021-05-17")).toBe("2021. 5. 17.");
    expect(formatPublisherCalendarDate("2021-02-29")).toBeNull();
    expect(formatPublisherCalendarDate("2021-05-17T00:00:00Z")).toBeNull();
    expect(formatPublisherCalendarDate(null)).toBeNull();
    expect(formatPublisherCalendarDate("not-a-date")).toBeNull();
  });

  it("keeps V1 producer wording while distinguishing partial and unknown V3 producers", async () => {
    const { describeProducerLine } = await import("@/app/field/registration-language");
    expect(describeProducerLine({ softwareName: "ODM", softwareVersion: "1" })).toBe("재구성 소프트웨어: ODM 1");
    expect(describeProducerLine({ softwareName: "ODM" })).toBe("재구성 소프트웨어: ODM");
    expect(describeProducerLine(null)).toBeNull();
    expect(describeProducerLine({ producerKnowledge: "DECLARED", softwareName: "DJI Terra", softwareVersion: "4.1.0" }))
      .toBe("재구성 소프트웨어: DJI Terra 4.1.0");
    expect(describeProducerLine({ producerKnowledge: "PARTIAL", softwareName: "DJI Terra", softwareVersion: null }))
      .toBe("재구성 소프트웨어: DJI Terra (버전 미상)");
    expect(describeProducerLine({ producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null }))
      .toBe("재구성 소프트웨어: 미상 (등록 시 확인되지 않음)");
  });

  it("shows date-only records with the calendar date and 시각 미상, never 촬영시각없음", async () => {
    const { describeCaptureLine } = await import("@/app/field/registration-language");
    const interval = (startedAt: string, endedAt: string) => `${startedAt}~${endedAt}`;
    // V1-shaped input without a basis stays silent: existing display unchanged.
    expect(describeCaptureLine({ captureStartedAt: "2026-09-08T01:00:00Z", captureEndedAt: "2026-09-08T01:10:00Z" }, interval)).toBeNull();
    expect(describeCaptureLine(null, interval)).toBeNull();
    expect(describeCaptureLine({ captureBasis: "UNKNOWN" }, interval)).toBe("촬영 시점: 미상 (등록 시 확인되지 않음)");
    const dateOnly = describeCaptureLine({ captureBasis: "DATE_ONLY", captureDate: "2021-05-17" }, interval);
    expect(dateOnly).toContain("2021. 5. 17.");
    expect(dateOnly).toContain("촬영 시각 미상");
    expect(dateOnly).not.toContain("촬영시각없음");
    expect(dateOnly).not.toContain("2021-05-17T");
    expect(describeCaptureLine({ captureBasis: "DATE_ONLY", captureDate: null }, interval)).toContain("날짜 확인 필요");
    expect(describeCaptureLine(
      { captureBasis: "EXACT_INTERVAL", captureStartedAt: "2026-09-08T01:00:00Z", captureEndedAt: "2026-09-08T01:10:00Z" },
      interval,
    )).toContain("2026-09-08T01:00:00Z");
  });

  it("labels retention loci without asserting publisher holding", async () => {
    const { describeRetentionLine } = await import("@/app/field/registration-language");
    expect(describeRetentionLine(null)).toBeNull();
    expect(describeRetentionLine({})).toBeNull();
    expect(describeRetentionLine({ originalRetentionLocus: "customer_workstation" })).toContain("고객 작업 장비");
    expect(describeRetentionLine({ originalRetentionLocus: "upstream_source" })).toContain("공개 출처(신고)");
    expect(describeRetentionLine({ originalRetentionLocus: "unknown" })).toContain("미상");
    expect(describeRetentionLine({ originalRetentionLocus: "upstream_source", originalRetentionDetail: "portal keeps originals" }))
      .toContain("portal keeps originals");
  });
});
