import { describe, expect, it } from "vitest";

import {
  analysisResultTitle,
  assetBusinessTitle,
  assetBusinessTitles,
  assetLifecycleLabel,
  capturePeriodTitle,
  compactFileName,
  dataKindLabel,
  dataRequestTitle,
  isSupportedDataKind,
  isSupportedLifecycleState,
  registrationVersionLabel,
} from "@/lib/operator-language";

function businessInput(overrides: {
  kind?: string;
  revision?: number;
  fileName?: string;
  startedAt?: string | null;
  endedAt?: string | null;
  assetRef?: string;
} = {}) {
  return {
    assetRef: overrides.assetRef ?? `ksa-v1-${"a".repeat(64)}`,
    kind: overrides.kind ?? "dsm",
    revision: overrides.revision ?? 1,
    declared: {
      fileName: overrides.fileName ?? "f03-ui-cycle-dsm-2.tif",
      captureStartedAt: overrides.startedAt ?? "2026-10-09T05:00:00Z",
      captureEndedAt: overrides.endedAt ?? "2026-10-09T05:30:00Z",
    },
  };
}

describe("operator language for registered materials", () => {
  it("leads business titles with data kind and actual capture, never the file name or revision", () => {
    const title = assetBusinessTitle(businessInput());

    expect(title).toBe("지표면 높이 자료(DSM) · 2026. 10. 9. 14:00–14:30 촬영");
    expect(title).not.toContain("f03-ui-cycle-dsm-2.tif");
    expect(title).not.toContain("f03");
    expect(title).not.toContain("revision");
    expect(title).not.toContain("등록 버전");
  });

  it("keeps the year so different years never look identical", () => {
    const thisYear = assetBusinessTitle(businessInput({ startedAt: "2026-10-09T05:00:00Z", endedAt: "2026-10-09T05:30:00Z" }));
    const lastYear = assetBusinessTitle(businessInput({ startedAt: "2025-10-09T05:00:00Z", endedAt: "2025-10-09T05:30:00Z" }));

    expect(thisYear).toContain("2026.");
    expect(lastYear).toContain("2025.");
    expect(thisYear).not.toBe(lastYear);
  });

  it("escalates to actual seconds before versions when only the minute format collides", () => {
    const first = businessInput({ assetRef: `ksa-v1-${"a".repeat(64)}`, startedAt: "2026-10-09T05:00:10Z", endedAt: "2026-10-09T05:30:10Z" });
    const second = businessInput({ assetRef: `ksa-v1-${"b".repeat(64)}`, startedAt: "2026-10-09T05:00:45Z", endedAt: "2026-10-09T05:30:45Z" });
    const titles = assetBusinessTitles([first, second]);

    expect(titles.get(first.assetRef)).not.toBe(titles.get(second.assetRef));
    expect(titles.get(first.assetRef)).toContain("14:00:10");
    expect(titles.get(second.assetRef)).toContain("14:00:45");
    expect(titles.get(first.assetRef)).not.toContain("등록 버전");
    expect(titles.get(second.assetRef)).not.toContain("등록 버전");
  });

  it("adapts DSM and DTM carefully without inventing geography", () => {
    expect(assetBusinessTitle(businessInput({ kind: "ortho" }))).toContain("정사영상");
    expect(dataKindLabel("dsm")).toBe("지표면 높이 자료(DSM)");
    expect(dataKindLabel("dtm")).toBe("지형 높이 자료(DTM)");
    expect(dataKindLabel("future-kind")).toBe("자료 종류 확인 필요");
    expect(isSupportedDataKind("dsm")).toBe(true);
    expect(isSupportedDataKind("future-kind")).toBe(false);
  });

  it("keeps unique choices free of version headlines", () => {
    const titles = assetBusinessTitles([
      businessInput({ assetRef: `ksa-v1-${"a".repeat(64)}` }),
      businessInput({ assetRef: `ksa-v1-${"b".repeat(64)}`, kind: "ortho" }),
    ]);

    expect(titles.get(`ksa-v1-${"a".repeat(64)}`)).not.toContain("등록 버전");
    expect(titles.get(`ksa-v1-${"b".repeat(64)}`)).not.toContain("등록 버전");
  });

  it("disambiguates same kind and capture with the actual registration version first", () => {
    const titles = assetBusinessTitles([
      businessInput({ assetRef: `ksa-v1-${"a".repeat(64)}`, revision: 1 }),
      businessInput({ assetRef: `ksa-v1-${"b".repeat(64)}`, revision: 2 }),
    ]);

    expect(titles.get(`ksa-v1-${"a".repeat(64)}`)).toContain("등록 버전 1");
    expect(titles.get(`ksa-v1-${"b".repeat(64)}`)).toContain("등록 버전 2");
  });

  function undatedInput(overrides: { assetRef: string; revision?: number; fileName: string }) {
    return {
      assetRef: overrides.assetRef,
      kind: "ortho",
      revision: overrides.revision ?? 1,
      declared: { fileName: overrides.fileName, captureStartedAt: null, captureEndedAt: null },
    };
  }

  it("disambiguates with the declared file name before any opaque reference", () => {
    const first = `ksa-v1-${"a".repeat(64)}`;
    const second = `ksa-v1-${"b".repeat(64)}`;
    const titles = assetBusinessTitles([
      undatedInput({ assetRef: first, fileName: "floreat-2021-ortho.tif" }),
      undatedInput({ assetRef: second, fileName: "floreat-2022-ortho.tif" }),
    ]);

    expect(titles.get(first)).not.toBe(titles.get(second));
    expect(titles.get(first)).toContain("floreat-2021-ortho.tif");
    expect(titles.get(second)).toContain("floreat-2022-ortho.tif");
    expect(titles.get(first)).not.toContain(first);
    expect(titles.get(second)).not.toContain(second);
    // 파일명은 식별용일 뿐 촬영 사실로 해석하지 않는다.
    expect(titles.get(first)).toContain("촬영 구간 미기재");
    expect(titles.get(first)).not.toContain("2021. ");
  });

  it("falls back to a brief deterministic id only when file names also collide", () => {
    const first = `ksa-v1-${"a".repeat(64)}`;
    const second = `ksa-v1-${"b".repeat(64)}`;
    const titles = assetBusinessTitles([
      businessInput({ assetRef: first, revision: 2, fileName: "same-name.tif" }),
      businessInput({ assetRef: second, revision: 2, fileName: "same-name.tif" }),
    ]);

    expect(titles.get(first)).not.toBe(titles.get(second));
    expect(titles.get(first)).toContain("same-name.tif");
    expect(titles.get(first)).toContain(`#${"a".repeat(8)}`);
    expect(titles.get(second)).toContain(`#${"b".repeat(8)}`);
    expect(titles.get(first)).not.toContain(first);
    expect(titles.get(second)).not.toContain(second);
    expect(titles.size).toBe(2);
  });

  it("does not merge distinct documents whose brief id suffixes also collide", () => {
    const first = `ksa-v1-${"a".repeat(56)}deadbeef`;
    const second = `ksa-v1-${"b".repeat(56)}deadbeef`;
    const titles = assetBusinessTitles([
      undatedInput({ assetRef: first, fileName: "same-name.tif" }),
      undatedInput({ assetRef: second, fileName: "same-name.tif" }),
    ]);
    expect(titles.get(first)).not.toBe(titles.get(second));
    expect(titles.get(first)).toContain(first);
    expect(titles.get(second)).toContain(second);
    expect(titles.size).toBe(2);
  });

  it("names registration versions without implying a shooting round or an original", () => {
    expect(registrationVersionLabel(2)).toBe("등록 버전 2");
    expect(registrationVersionLabel(2)).not.toMatch(/회차|촬영|원본|최초/);
  });

  it("states submission truthfully without claiming inspection or accuracy approval", () => {
    expect(assetLifecycleLabel("SEALED")).toBe("파일 제출 완료");
    expect(assetLifecycleLabel("UNSEALED")).toBe("파일 제출 미완료");
    expect(assetLifecycleLabel("SUPERSEDED")).toBe("이전 등록 자료");
    expect(assetLifecycleLabel("SEALED")).not.toMatch(/검증|승인|정확도/);
    expect(assetLifecycleLabel("SOME_FUTURE_STATE")).toBe("상태 확인 필요");
    expect(isSupportedLifecycleState("SEALED")).toBe(true);
    expect(isSupportedLifecycleState("SOME_FUTURE_STATE")).toBe(false);
  });

  it("titles capture periods with the year and without ever calling them a cycle number", () => {
    expect(capturePeriodTitle("2026-10-09T05:00:00Z", "2026-10-09T05:30:00Z")).toBe("2026. 10. 9. 14:00–14:30 촬영");
    expect(capturePeriodTitle("2026-10-09T04:00:00Z", "2026-10-10T00:30:00Z")).toContain("촬영");
    expect(capturePeriodTitle("2026-10-09T05:00:00Z", null)).toContain("종료 미기재");
    expect(capturePeriodTitle("not-a-date", "also-bad")).toBe("촬영 구간 확인 불가");
    expect(capturePeriodTitle("2026-10-09T05:00:10Z", "2026-10-09T05:30:10Z", { seconds: true })).toContain("14:00:10");
  });

  it("titles analysis and request records by their own creation day, never as capture", () => {
    expect(analysisResultTitle("2026-10-15T12:31:00Z")).toBe("10월 15일 분석 결과");
    expect(dataRequestTitle("2026-10-14T10:40:09Z")).toBe("10월 14일 데이터 요청 기록");
    expect(analysisResultTitle("not-a-date")).toBe("분석 결과");
    expect(dataRequestTitle("not-a-date")).toBe("데이터 요청 기록");
  });

  it("shortens awkward file names for layout without translating them", () => {
    expect(compactFileName("short.tif")).toBe("short.tif");
    const longAscii = `f03-ui-cycle-very-long-synthetic-rig-name-that-keeps-going-${"x".repeat(40)}.tif`;
    const compacted = compactFileName(longAscii);
    expect(compacted.length).toBeLessThan(longAscii.length);
    expect(compacted).toContain("…");
    expect(compacted.endsWith(".tif")).toBe(true);
    const unicode = `현장관측자료_북측작업구역_지표면높이_${"관".repeat(40)}.tif`;
    expect([...compactFileName(unicode)].length).toBeLessThanOrEqual(48);
    expect(compactFileName("no-extension-at-all-" + "y".repeat(60))).toContain("…");
  });
});
