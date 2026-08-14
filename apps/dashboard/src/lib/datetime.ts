/**
 * 한국 시각 표기 — **서버 로컬 시간대에 기대지 않는다.**
 *
 * 현장은 한국이고 서버는 어디서든 돌 수 있다(이 저장소의 배포 구성은 컨테이너
 * 시간대를 고정하지 않는다, `deploy/`에 `TZ=` 선언이 없다). `Date.toLocaleString`을
 * `timeZone` 없이 부르면 그 값은 **서버가 도는 시간대**로 나온다 — 서버가 UTC로
 * 뜨면(흔한 컨테이너 기본값) 화면에 찍히는 시각이 실제 한국 시각과 9시간
 * 어긋난다. 자정 근처에서는 **날짜 자체**가 바뀐다(예: 한국 시각 08:30 계산이
 * UTC 서버에서는 "전날 23:30"으로 찍힌다) — "기준 시점이 언제였는지"가 이
 * 화면(M4-C 진척)의 핵심 주장이라 이 어긋남은 사소하지 않다.
 *
 * `TopBar.tsx`가 이미 이 문제를 알고 `Asia/Seoul`을 명시해 왔다(오늘 날짜
 * 표시). 이 모듈은 그 규율을 한 곳으로 모아, 계산 시각을 찍는 다른 화면들
 * (진척·설계면·비교 제출·설계 대비 잔량)이 매번 새로 알아내지 않게 한다.
 */

export const SEOUL_TIME_ZONE = "Asia/Seoul";

type DatePart = "year" | "month" | "day" | "hour" | "minute" | "second" | "weekday";

/**
 * 서버(Node ICU)와 브라우저 ICU가 같은 `ko-KR`에도 오전/오후 위치를 다르게 출력해
 * hydration을 깨뜨린 일이 있었다. `Intl`에게 문자열 전체를 맡기지 않고, 서울 시간의
 * 숫자 part만 얻어 제품이 소유하는 순서로 조립한다. 따라서 SSR과 Client Component가
 * 같은 ISO 값을 받으면 런타임 ICU 구현 차이와 관계없이 같은 문자열을 낸다.
 */
function seoulParts(value: Date): Record<DatePart, string> {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: SEOUL_TIME_ZONE,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    weekday: "long",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value);

  const collected = Object.fromEntries(
    parts
      .filter((part): part is Intl.DateTimeFormatPart & { type: DatePart } =>
        ["year", "month", "day", "hour", "minute", "second", "weekday"].includes(part.type),
      )
      .map((part) => [part.type, part.value]),
  ) as Partial<Record<DatePart, string>>;

  // 위 formatter 옵션은 모든 값을 반드시 내지만, fallback은 잘못된/부분 ICU가 화면을
  // 통째로 죽이는 대신 원문보다 읽기 쉬운 UTC 시간으로 보이게 하는 마지막 방어다.
  return {
    year: collected.year ?? String(value.getUTCFullYear()),
    // 한국어 화면의 날짜는 08월/08일보다 8월/8일로 쓰는 기존 제품 표기를 따른다.
    // formatter가 두 자릿수를 주어도 숫자로 한 번 정규화해 런타임별 padding 차이를 없앤다.
    month: String(Number(collected.month ?? value.getUTCMonth() + 1)),
    day: String(Number(collected.day ?? value.getUTCDate())),
    hour: collected.hour ?? String(value.getUTCHours()).padStart(2, "0"),
    minute: collected.minute ?? String(value.getUTCMinutes()).padStart(2, "0"),
    second: collected.second ?? String(value.getUTCSeconds()).padStart(2, "0"),
    weekday: collected.weekday ?? "",
  };
}

const WEEKDAY_KO: Record<number, string> = {
  0: "일요일",
  1: "월요일",
  2: "화요일",
  3: "수요일",
  4: "목요일",
  5: "금요일",
  6: "토요일",
};

function hasTime(options: Intl.DateTimeFormatOptions): boolean {
  return (
    options.timeStyle !== undefined ||
    options.hour !== undefined ||
    options.minute !== undefined ||
    options.second !== undefined
  );
}

function hasDate(options: Intl.DateTimeFormatOptions): boolean {
  return (
    options.dateStyle !== undefined ||
    options.year !== undefined ||
    options.month !== undefined ||
    options.day !== undefined ||
    options.weekday !== undefined
  );
}

/** 서울 날짜만, Node/브라우저가 바뀌어도 같은 한글 표기로 반환한다. */
export function formatKoreanDate(iso: string, withWeekday = false): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const parts = seoulParts(when);
  const date = `${parts.year}. ${parts.month}. ${parts.day}.`;
  if (!withWeekday) return date;
  // `parts.weekday`는 formatter locale에 따라 English가 될 수 있다. 이미 얻은 서울
  // 연·월·일을 UTC의 달력 날짜로 해석하면 요일만 안정적으로 구할 수 있다.
  const weekday = new Date(
    Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)),
  ).getUTCDay();
  return `${date} ${WEEKDAY_KO[weekday]}`;
}

/**
 * ISO 문자열을 서울 기준의 결정론적 문자열로. `Intl.DateTimeFormat` 옵션의 필요한
 * 부분만 호환한다. 기본값은 날짜+초, `dateStyle/timeStyle: medium/short`은 날짜+분을
 * 쓴다. 파싱할 수 없으면 원문을 그대로 돌려준다.
 */
export function formatKoreanDateTime(
  iso: string,
  options?: Intl.DateTimeFormatOptions,
): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  const normalized = options ?? {};
  const showDate = options === undefined || hasDate(normalized);
  const showTime = options === undefined || hasTime(normalized);
  const parts = seoulParts(when);
  const includeSeconds =
    options === undefined || normalized.timeStyle === "medium" || normalized.second !== undefined;
  const date = showDate ? `${parts.year}. ${parts.month}. ${parts.day}.` : "";
  const time = showTime
    ? `${parts.hour}:${parts.minute}${includeSeconds ? `:${parts.second}` : ""}`
    : "";

  if (date && time) return `${date} ${time}`;
  return date || time || `${parts.year}. ${parts.month}. ${parts.day}. ${parts.hour}:${parts.minute}:${parts.second}`;
}
