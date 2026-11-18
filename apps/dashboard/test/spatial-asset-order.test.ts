import { describe, expect, it } from "vitest";

import { sortByCaptureDescending } from "@/lib/spatial-asset-order";

type Item = Parameters<typeof sortByCaptureDescending>[0][number];

function item(assetRef: string, captureStartedAt: string | null, captureDate: string | null = null): Item {
  return { assetRef, declared: { captureStartedAt, captureDate } } as Item;
}

const order = (items: readonly Item[]) => sortByCaptureDescending(items).map((entry) => entry.assetRef);

describe("sortByCaptureDescending", () => {
  it("촬영이 늦은 자료를 위로 둔다(Core의 자료 참조 순서와 무관하게)", () => {
    expect(order([
      item("ksa-v1-a", "2019-08-20T01:00:00Z"),
      item("ksa-v1-b", "2022-08-24T01:00:00Z"),
      item("ksa-v1-c", "2021-08-17T01:00:00Z"),
    ])).toEqual(["ksa-v1-b", "ksa-v1-c", "ksa-v1-a"]);
  });

  it("촬영 시각이 없으면 촬영 날짜로 비교하고, 시점을 모르는 자료는 맨 아래에 둔다", () => {
    expect(order([
      item("ksa-v1-a", null),
      item("ksa-v1-b", null, "2020-01-01"),
      item("ksa-v1-c", "2021-08-17T01:00:00Z"),
      item("ksa-v1-d", "읽을 수 없는 값"),
    ])).toEqual(["ksa-v1-c", "ksa-v1-b", "ksa-v1-a", "ksa-v1-d"]);
  });

  it("같은 시점은 자료 참조 순으로 고정하고 입력 배열을 바꾸지 않는다", () => {
    const input = [item("ksa-v1-z", "2021-08-17T01:00:00Z"), item("ksa-v1-a", "2021-08-17T01:00:00Z")];
    expect(order(input)).toEqual(["ksa-v1-a", "ksa-v1-z"]);
    expect(input.map((entry) => entry.assetRef)).toEqual(["ksa-v1-z", "ksa-v1-a"]);
  });
});
