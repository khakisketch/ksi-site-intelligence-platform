/** 작업 이름을 비워 두면 쓰는 기본 이름: "{구역} · {한국 날짜} 자료". 현장 사용자가 이름을 짓지 않아도 목록에서 알아볼 수 있게 한다. */

const MAX_NAME = 200;

export function koreanCalendarDate(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")}`;
}

export function defaultObservationName(areaNames: readonly string[], now: Date): string {
  const names = areaNames.map((name) => name.trim()).filter((name) => name.length > 0);
  const suffix = ` · ${koreanCalendarDate(now)} 자료`;
  if (names.length === 0) return `${koreanCalendarDate(now)} 자료`;
  const lead = names.length === 1 ? names[0] : `${names[0]} 외 ${names.length - 1}곳`;
  const room = MAX_NAME - suffix.length;
  const bounded = lead.length > room ? `${lead.slice(0, Math.max(0, room - 1)).trimEnd()}…` : lead;
  return `${bounded}${suffix}`;
}
