import { describe, expect, it } from "vitest";

import {
  formatBytesKo,
  formatCountKo,
  formatNumberKo,
  formatSignificantKo,
} from "@/lib/number-format";

// 화면 숫자 표기의 단일 규칙이다. 판정은 여기 없다 — 값은 서버 계약이 이미
// 검증했고, 여기서는 사람이 읽는 문자열로 옮기는 규칙만 고정한다.

describe("formatNumberKo", () => {
  it("[핵심] 음의 0 은 0 으로 보여준다", () => {
    expect(formatNumberKo(-0)).toBe("0");
    expect(formatNumberKo(-0, 2)).toBe("0");
  });

  it("표시 정밀도에서 0으로 반올림되는 음수는 부호를 숨기되 실제 음수는 유지한다", () => {
    expect(formatNumberKo(-0.0001, 2)).toBe("0");
    expect(formatNumberKo(-1.25, 2)).toBe("-1.25");
  });

  it("묶음 표기와 소수 자리 제한", () => {
    expect(formatNumberKo(1234.567)).toBe("1,234.6");
    expect(formatNumberKo(1234.5, 2)).toBe("1,234.5");
  });
});

describe("formatSignificantKo", () => {
  it("정밀도가 앞자리에 걸리는 값(작은 GSD 등)은 유효숫자로 자른다", () => {
    expect(formatSignificantKo(0.12345, 4)).toBe("0.1235");
    expect(formatSignificantKo(0.04, 3)).toBe("0.04");
  });

  it("0 은 그대로 0 이다", () => {
    expect(formatSignificantKo(0, 3)).toBe("0");
  });
});

describe("formatCountKo / formatBytesKo", () => {
  it("개수는 소수점 없이 묶음 표기", () => {
    expect(formatCountKo(4321)).toBe("4,321");
    expect(formatCountKo(4)).toBe("4");
  });

  it("바이트는 정수 묶음 + bytes 단위", () => {
    expect(formatBytesKo(4321)).toBe("4,321 bytes");
    expect(formatBytesKo(0)).toBe("0 bytes");
    expect(formatBytesKo(-0)).toBe("0 bytes");
  });
});
