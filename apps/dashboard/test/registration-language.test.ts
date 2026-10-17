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
