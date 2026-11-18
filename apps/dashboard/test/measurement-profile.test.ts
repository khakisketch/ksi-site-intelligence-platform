import { describe, expect, it } from "vitest";

import type { ProfileSample } from "@/lib/core-api/measurement-types";
import {
  countUnknown,
  crsLabel,
  formatSigned,
  knownRuns,
  nearestSample,
  profileCsv,
  readRange,
  unknownLabel,
  verticalScale,
} from "@/lib/measurement-profile";

function sample(index: number, distanceM: number, elevationM: number | null, reason: ProfileSample["invalidReason"] = null): ProfileSample {
  return { index, distanceM, x: 200000 + distanceM, y: 500000, elevationM, invalidReason: elevationM === null ? (reason ?? "NODATA") : null };
}

// z = 100 + 0.5 * d 인 평면. 값 없는 지점이 끼어도 처음과 끝의 유효 값으로 기울기를 읽는다.
const plane: ProfileSample[] = [
  sample(0, 0, null, "INSUFFICIENT_NEIGHBORS"),
  sample(1, 1, 100.5),
  sample(2, 2, 101),
  sample(3, 3, null, "NODATA"),
  sample(4, 4, 102),
  sample(5, 5, 102.5),
  sample(6, 6, null, "OUTSIDE_SURFACE"),
];

describe("knownRuns", () => {
  it("값 없는 지점에서 선을 끊는다(0이나 이웃 값으로 잇지 않는다)", () => {
    const runs = knownRuns(plane);
    expect(runs.map((run) => run.map((row) => row.index))).toEqual([[1, 2], [4, 5]]);
  });

  it("모두 모르면 빈 배열이다", () => {
    expect(knownRuns([sample(0, 0, null), sample(1, 1, null)])).toEqual([]);
  });
});

describe("countUnknown", () => {
  it("이유별로 센다", () => {
    expect(countUnknown(plane)).toEqual({ outside: 1, edge: 1, nodata: 1, total: 3 });
  });
});

describe("unknownLabel", () => {
  it("사람이 읽는 말로 바꾼다", () => {
    expect(unknownLabel("OUTSIDE_SURFACE")).toBe("범위 밖");
    expect(unknownLabel("INSUFFICIENT_NEIGHBORS")).toBe("가장자리");
    expect(unknownLabel("NODATA")).toBe("자료 없음");
  });
});

describe("nearestSample", () => {
  it("가장 가까운 거리의 지점을 돌려준다", () => {
    expect(nearestSample(plane, 2.4)?.index).toBe(2);
    expect(nearestSample(plane, 2.6)?.index).toBe(3);
    expect(nearestSample(plane, -5)?.index).toBe(0);
    expect(nearestSample(plane, 99)?.index).toBe(6);
  });
  it("빈 배열이면 null", () => {
    expect(nearestSample([], 1)).toBeNull();
  });
});

describe("readRange", () => {
  it("처음과 끝의 유효 값으로 높이 차와 기울기를 읽는다", () => {
    // 1~5 m 구간: 100.5 -> 102.5, 4 m 동안 +2 m = 50 %
    const reading = readRange(plane, 1, 5);
    expect(reading).not.toBeNull();
    expect(reading!.lengthM).toBeCloseTo(4, 10);
    expect(reading!.heightChangeM).toBeCloseTo(2, 10);
    expect(reading!.gradePercent).toBeCloseTo(50, 10);
  });

  it("끝점이 값 없음이면 구간 안의 가장 가까운 유효 값을 쓴다", () => {
    // 0~6 m: 유효 처음 1 m(100.5), 유효 끝 5 m(102.5)
    const reading = readRange(plane, 0, 6);
    expect(reading!.heightChangeM).toBeCloseTo(2, 10);
    expect(reading!.gradePercent).toBeCloseTo(50, 10);
    expect(reading!.lengthM).toBeCloseTo(6, 10);
  });

  it("내리막은 음수다", () => {
    const down = [sample(0, 0, 10), sample(1, 2, 9)];
    expect(readRange(down, 0, 2)!.gradePercent).toBeCloseTo(-50, 10);
  });

  it("유효 지점이 둘보다 적으면 null이다(값을 만들어 내지 않는다)", () => {
    expect(readRange(plane, 3, 3.5)).toBeNull();
    expect(readRange(plane, 1.2, 1.8)).toBeNull();
    expect(readRange([sample(0, 0, null), sample(1, 1, null)], 0, 1)).toBeNull();
  });

  it("순서를 바꿔 줘도 같은 구간이다", () => {
    expect(readRange(plane, 5, 1)).toEqual(readRange(plane, 1, 5));
  });
});

describe("verticalScale", () => {
  const runs = [[sample(0, 0, 112), sample(1, 28, 115)]];

  it("맞춤: 유효 값 전체를 여유와 함께 덮는다", () => {
    const scale = verticalScale(runs, "fit", 308, 180, 28);
    expect(scale).not.toBeNull();
    expect(scale!.lo).toBeLessThan(112);
    expect(scale!.hi).toBeGreaterThan(115);
    expect(scale!.ticks.length).toBeGreaterThanOrEqual(2);
    for (const tick of scale!.ticks) {
      expect(tick).toBeGreaterThanOrEqual(scale!.lo);
      expect(tick).toBeLessThanOrEqual(scale!.hi);
    }
  });

  it("1:1: 가로 1 m와 세로 1 m가 같은 화면 길이가 된다", () => {
    const scale = verticalScale(runs, "true", 308, 180, 28);
    // 가로 308 px / 28 m = 11 px/m 이므로 세로 180 px 는 정확히 180 / 11 m 를 덮는다.
    expect(scale!.hi - scale!.lo).toBeCloseTo(180 / 11, 10);
    // 값의 가운데가 범위의 가운데다.
    expect((scale!.hi + scale!.lo) / 2).toBeCloseTo((112 + 115) / 2, 10);
  });

  it("유효 값이 없으면 null", () => {
    expect(verticalScale([], "fit", 308, 180, 28)).toBeNull();
  });
});

describe("profileCsv", () => {
  it("모르는 지점은 빈 칸과 이유 코드로 보낸다(0으로 채우지 않는다)", () => {
    const csv = profileCsv([{ label: "기준 2026-03-14", samples: plane.slice(0, 4) }]);
    const lines = csv.replace(/^﻿/, "").trim().split("\r\n");
    expect(lines[0]).toBe("series,distance_m,x,y,elevation_m,unknown_reason,vertical_reference");
    expect(lines[1]).toBe('"기준 2026-03-14",0,200000,500000,,INSUFFICIENT_NEIGHBORS,""');
    expect(lines[2]).toBe('"기준 2026-03-14",1,200001,500000,100.5,,""');
    expect(lines[4]).toBe('"기준 2026-03-14",3,200003,500000,,NODATA,""');
  });

  it("수직 기준 출처를 모든 행에 싣는다(선언은 선언이라고 표시한다)", () => {
    const csv = profileCsv([
      { label: "기준", samples: plane.slice(0, 2), vertical: "observed:EPSG:5773" },
      { label: "현재", samples: plane.slice(0, 2), vertical: "declared:orthometric_kngeoid2018" },
    ]);
    const lines = csv.replace(/^﻿/, "").trim().split("\r\n").slice(1);
    expect(lines.filter((line) => line.endsWith(',"observed:EPSG:5773"'))).toHaveLength(2);
    expect(lines.filter((line) => line.endsWith(',"declared:orthometric_kngeoid2018"'))).toHaveLength(2);
  });

  it("Excel이 한글을 읽도록 BOM으로 시작한다", () => {
    expect(profileCsv([{ label: "a", samples: plane }]).startsWith("﻿")).toBe(true);
  });

  it("라벨의 따옴표를 이스케이프한다", () => {
    const csv = profileCsv([{ label: 'a"b', samples: [sample(0, 0, 1), sample(1, 1, 2)] }]);
    expect(csv).toContain('"a""b",0,');
  });

  it("수식으로 읽힐 수 있는 라벨 앞에 따옴표를 붙여 무력화한다", () => {
    const csv = profileCsv([{ label: "=1+1", samples: [sample(0, 0, 1), sample(1, 1, 2)] }]);
    expect(csv).toContain("\"'=1+1\"");
  });
});

describe("crsLabel", () => {
  it("한국 좌표계 이름을 붙인다", () => {
    expect(crsLabel("EPSG:5186")).toBe("한국 중부원점 TM · EPSG:5186");
    expect(crsLabel("EPSG:5179")).toBe("한국 통합 TM · EPSG:5179");
  });
  it("모르는 좌표계는 코드만 쓴다", () => {
    expect(crsLabel("EPSG:32652")).toBe("EPSG:32652");
  });
});

describe("formatSigned", () => {
  it("부호를 항상 붙이고 음수는 진짜 빼기 기호를 쓴다", () => {
    expect(formatSigned(1.234, 2)).toBe("+1.23");
    expect(formatSigned(-1.234, 2)).toBe("−1.23");
    expect(formatSigned(0, 1)).toBe("+0.0");
  });
});
