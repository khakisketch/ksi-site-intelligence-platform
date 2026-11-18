import type { ProfileVerticalReference, VerticalDatum } from "@/lib/core-api/measurement-types";

/**
 * 단면 높이가 어떤 수직 기준 위에서 읽혔는지 사람 말로 옮긴다.
 * 파일에서 확인한 값(관측)과 사용자가 선언한 값(주장)은 말투와 표시에서 항상 갈라 둔다.
 * 선언을 정확하다거나 검증됐다고 말하지 않는다(INV-024, INV-040).
 */

const DATUM_LABEL: Record<VerticalDatum, string> = {
  ellipsoidal: "타원체고",
  ellipsoidal_native: "타원체고(변환 없이 그대로)",
  orthometric_kngeoid2018: "정표고(KNGeoid2018)",
  orthometric_kngeoid2024: "정표고(KNGeoid2024)",
};

export function datumLabel(datum: VerticalDatum): string {
  return DATUM_LABEL[datum];
}

export interface VerticalText {
  kind: "observed" | "declared" | "unknown";
  /** 한 줄 요약. 출처가 앞에 온다. */
  text: string;
}

export function verticalText(reference: ProfileVerticalReference | null | undefined): VerticalText {
  if (!reference) return { kind: "unknown", text: "수직 기준 확인 불가" };
  if (reference.provenance === "OBSERVED") {
    return { kind: "observed", text: `파일에서 확인 · ${reference.observed.identifier}` };
  }
  return { kind: "declared", text: `사용자 선언 · ${datumLabel(reference.declared.datum)}` };
}

/** CSV 한 열. 기계가 읽는 값이라 한국어 말투를 쓰지 않는다. */
export function verticalCsvCode(reference: ProfileVerticalReference | null | undefined): string {
  if (!reference) return "";
  if (reference.provenance === "OBSERVED") return `observed:${reference.observed.identifier}`;
  return `declared:${reference.declared.datum}`;
}

/**
 * 두 날짜의 높이를 그대로 비교해도 되는 기준인가.
 * 같은 출처이고 같은 기준일 때만 true다. 한쪽이 선언이고 다른 쪽이 관측이면 같은 이름이어도 true로 보지 않는다.
 * 알 수 없으면 null이며, 호출자는 비교해도 된다고 말하지 않는다.
 */
export function verticalsComparable(
  a: ProfileVerticalReference | null | undefined,
  b: ProfileVerticalReference | null | undefined,
): boolean | null {
  if (!a || !b) return null;
  if (a.provenance !== b.provenance) return false;
  if (a.provenance === "OBSERVED" && b.provenance === "OBSERVED") {
    return a.observed.identifier === b.observed.identifier;
  }
  if (a.provenance === "DECLARED" && b.provenance === "DECLARED") {
    return a.declared.datum === b.declared.datum;
  }
  return false;
}
