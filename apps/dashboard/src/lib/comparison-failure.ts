/**
 * 비교 실패 사유를 **운영자가 읽는 문장**으로 — 원문은 버리지 않는다.
 *
 * 워커가 남기는 `detail` 은 계산 쪽 사람에게 정확한 진단이지만, 화면에서 그대로
 * 첫 문장이 되면 운영자는 손댈 수 없는 말을 읽는다. 2026-08-18 실제 파이프라인
 * 종단 실행에서 그대로 드러났다:
 *
 *   "EPSG:32617 은 지원 투영좌표계가 아니다 — 허용: ['EPSG:5179', 'EPSG:5185', …].
 *    구 측지계(Bessel, EPSG:5173~5177)를 현행 KGD2002 와 섞으면 …"
 *
 * 이 문장은 **왜 실패했는지**를 정확히 말하지만 **무엇을 하라는지**는 말하지 않고,
 * 읽는 사람이 좌표계 세대 문제를 알고 있어야 이해된다.
 *
 * 그래서 두 층으로 나눈다: 앞에는 무슨 일이 있었고 무엇을 해야 하는지, 뒤에는
 * 서버가 준 원문을 그대로(근거를 지우지 않는다 — 이 값이 있어야 계산 담당자가
 * 같은 화면을 보고 원인을 짚는다).
 *
 * 알아보지 못하는 사유는 **번역하지 않는다** — 지어낸 요약보다 원문이 낫다.
 */
export interface ComparisonFailureText {
  /** 운영자용 한 문장 — 무엇이 안 됐고 다음에 무엇을 할 수 있는가. */
  summary: string;
  /** 서버가 준 원문. 요약이 원문과 같아지는 경우에는 null(같은 말을 두 번 쓰지 않는다). */
  evidence: string | null;
}

/** 좌표계 계열 실패 — 지원 밖 투영좌표계로 만들어진 산출물끼리는 비교하지 않는다. */
const UNSUPPORTED_CRS = /지원 투영좌표계가 아니다|UnsupportedCrs/i;
/** 두 시점의 좌표계가 서로 다른 경우 — 빼기 자체가 성립하지 않는다. */
const CRS_MISMATCH = /좌표계가 다르다|CrsMismatch/i;
/** 구역 안에 유효한 셀이 없다 — 구역을 잘못 그렸거나 촬영 범위 밖이다. */
const EMPTY_ZONE = /유효한 (높이자료|셀)|구역 안에/;

export function describeComparisonFailure(detail: string | null): ComparisonFailureText {
  if (!detail || !detail.trim()) {
    return {
      summary:
        "비교에 실패했습니다. 서버가 사유를 기록하지 않아 원인을 알 수 없습니다 — 임무 화면에서 다시 요청해 보세요.",
      evidence: null,
    };
  }

  if (UNSUPPORTED_CRS.test(detail)) {
    return {
      summary:
        "이 두 재구성 결과의 좌표계가 이 시스템이 다루는 한국 좌표계가 아니어서 비교하지 않았습니다. " +
        "좌표계가 다르면 두 시점의 높이를 그대로 빼는 계산이 성립하지 않아, 그럴듯해 보이는 틀린 값이 나옵니다.",
      evidence: detail,
    };
  }

  if (CRS_MISMATCH.test(detail)) {
    return {
      summary:
        "두 시점의 좌표계가 서로 달라 비교하지 않았습니다. 같은 좌표계로 만들어진 두 재구성끼리만 비교할 수 있습니다.",
      evidence: detail,
    };
  }

  if (EMPTY_ZONE.test(detail)) {
    return {
      summary:
        "고른 구역 안에 비교할 높이자료가 없습니다. 구역이 촬영 범위를 벗어났는지 확인하고 다시 그려 요청하세요.",
      evidence: detail,
    };
  }

  // 모르는 사유 — 원문을 그대로 첫 문장으로 쓴다(요약을 지어내지 않는다).
  return { summary: detail, evidence: null };
}
