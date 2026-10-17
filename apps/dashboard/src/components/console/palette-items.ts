/** 커맨드 팔레트의 검색 대상과 순위 판정 — 순수 로직(렌더 없음).
 *
 * 이 파일이 순수한 이유는 이 저장소의 프런트 테스트 규약 때문이다(vitest.config.ts):
 * 렌더링은 실캡처로 검증하고 vitest 는 판정 로직만 본다. 팔레트에서 "무엇이 검색되고
 * 어떤 순서로 나오는가"가 그 판정이다.
 *
 * 디자인 근거: `KSI Console v2.dc.html` §0 앱 셸 — ⌘K 팔레트는 화면·현장·변화 영역·
 * 임무 계약 ID·정확도·공정을 한 입구에서 찾는다. 지금 구현은 그중 **화면과 현장**만
 * 덮는다. 나머지 축(변화 영역·계약 ID)은 그 데이터를 셸이 아직 들고 있지 않아
 * 넣지 않았다 — 없는 걸 있는 것처럼 비워 두지 않는다(INV-040 의 정신).
 */

export interface PaletteItem {
  /** 라우팅 키 — 중복 제거·React key 로 쓴다. */
  key: string;
  /** 사용자가 읽는 이름. 검색 대상. */
  label: string;
  /** 어느 갈래인지(화면/현장). 그룹 머리말로 쓴다. */
  group: string;
  href: string;
  /** 라벨 밑에 붙는 보조 문구(현장 ID·상태 등). 검색 대상에 포함된다. */
  hint?: string;
  /** 검색용 원문·동의어. 화면 설명에는 기술 식별자를 반복하지 않는다. */
  keywords?: string;
  /** 준비 중 항목 — 목록에서 숨기지 않고 상태를 밝힌다(UX 목표 §6). */
  pending?: boolean;
}

/** 검색어 정규화 — 대소문자·좌우 공백만 없앤다.
 *
 * 한글 초성 검색은 하지 않는다. 자모 분해는 라이브러리 없이 정확히 하기 어렵고,
 * 어설프게 넣으면 "ㅅㅈ"이 엉뚱한 항목을 올리는 쪽이 더 나쁘다. */
export function normalizeQuery(raw: string): string {
  return raw.trim().toLowerCase();
}

/** 한 항목이 검색어에 얼마나 맞는가 — 낮을수록 먼저 온다. 안 맞으면 null.
 *
 * 순위는 세 단계뿐이다: 라벨 시작 일치(0) · 라벨 부분 일치(1) · 보조 문구 일치(2).
 * 더 정교한 점수(편집거리 등)를 넣지 않는 것은 의도다 — 항목이 수십 개 규모라
 * 정교함이 체감되지 않고, 규칙이 단순해야 "왜 이게 위에 있나"를 설명할 수 있다.
 */
export function matchScore(item: PaletteItem, query: string): number | null {
  if (!query) return 0;
  const label = item.label.toLowerCase();
  if (label.startsWith(query)) return 0;
  if (label.includes(query)) return 1;
  if (item.hint && item.hint.toLowerCase().includes(query)) return 2;
  if (item.keywords && item.keywords.toLowerCase().includes(query)) return 2;
  return null;
}

/** 검색어로 거른 뒤 순위·원래 순서로 정렬한다. 빈 검색어면 전부 원래 순서. */
export function filterPaletteItems(items: PaletteItem[], rawQuery: string): PaletteItem[] {
  const query = normalizeQuery(rawQuery);
  const scored: Array<{ item: PaletteItem; score: number; index: number }> = [];
  items.forEach((item, index) => {
    const score = matchScore(item, query);
    if (score !== null) scored.push({ item, score, index });
  });
  // 동점이면 입력 순서를 유지한다 — 정렬이 안정적이지 않으면 같은 검색어에
  // 다른 순서가 나와 "화면이 흔들린다"로 읽힌다.
  scored.sort((a, b) => (a.score === b.score ? a.index - b.index : a.score - b.score));
  return scored.map((entry) => entry.item);
}

/** 위/아래 이동 — 목록 끝에서 멈춘다(순환하지 않는다).
 *
 * 순환시키지 않는 이유: 끝에서 한 번 더 누르면 처음으로 튀는 동작은 목록이 긴
 * 화면에서 "어디에 있는지" 감각을 깨뜨린다. 팔레트는 훑는 도구이지 회전목마가 아니다. */
export function moveActiveIndex(current: number, delta: number, length: number): number {
  if (length === 0) return 0;
  return Math.min(length - 1, Math.max(0, current + delta));
}
