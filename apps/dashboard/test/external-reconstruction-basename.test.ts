import { describe, expect, it } from "vitest";

import {
  describeExternalBasenameIssue,
  isSupportedExternalBasename,
} from "@/lib/external-reconstruction-basename";

describe("external reconstruction basename preflight", () => {
  it.each([
    "ortho.tif",
    "DSM_2026-09-06.TIF",
    "a",
    "0-leading-digit.tif",
    "under_score-hyphen.dot.tif",
    "Z9_.-",
    "a".repeat(251) + ".tif",
  ])("accepts contract-valid ASCII basename %s", (fileName) => {
    expect(describeExternalBasenameIssue(fileName)).toBeNull();
    expect(isSupportedExternalBasename(fileName)).toBe(true);
  });

  it.each([
    ["", "비어"],
    [".hidden.tif", "시작"],
    [" ortho.tif", "공백"],
    ["a/b.tif", "폴더"],
    ["a\\b.tif", "폴더"],
    ["my ortho.tif", "공백"],
    ["정사영상.tif", "영문 외"],
    ["한글_DSM.tif", "영문 외"],
    [`${"a".repeat(252)}.tif`, "255자"],
    ["ortho#.tif", "밑줄"],
    ["café.tif", "영문 외"],
  ])("rejects %s with guidance", (fileName, fragment) => {
    const issue = describeExternalBasenameIssue(fileName);
    expect(issue).not.toBeNull();
    expect(issue).toContain(fragment);
    expect(isSupportedExternalBasename(fileName)).toBe(false);
  });

  it("never truncates or rewrites the original name", () => {
    const long = `관측_${"가".repeat(300)}.tif`;
    expect(describeExternalBasenameIssue(long)).toContain("255자");
    expect(long.length).toBeGreaterThan(255);
  });
});
