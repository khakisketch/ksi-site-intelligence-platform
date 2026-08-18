/** 전역 단축키 판정 — 순수 함수(이벤트 리스너 없음).
 *
 * 디자인 근거: `KSI Console v2.dc.html` §Interactions —
 * `⌘K`/`Ctrl+K` 팔레트 · `?` 도움말 · `Esc` 닫기.
 *
 * 판정을 리스너에서 분리한 이유는 **입력 중 가로채기**가 이 기능에서 가장 깨지기 쉬운
 * 자리이기 때문이다. 사용자가 검색창에 "?"를 치는 순간 도움말이 열리면 그건 버그이고,
 * 그 회귀는 렌더 캡처로는 안 잡힌다. 순수 판정이면 테스트가 고정한다.
 */

export type ShortcutAction = "palette" | "help" | "close" | null;

/** 키 입력이 일어난 자리가 "글자를 받는 곳"인가.
 *
 * `contentEditable` 까지 보는 이유: 주석·메모 입력이 그 형태로 들어올 수 있고,
 * 그때 `?` 를 삼키면 사용자가 물음표를 못 쓴다. */
export function isTypingTarget(target: {
  tagName?: string;
  isContentEditable?: boolean;
} | null): boolean {
  if (!target) return false;
  if (target.isContentEditable) return true;
  const tag = (target.tagName || "").toUpperCase();
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export interface ShortcutEventLike {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  target?: { tagName?: string; isContentEditable?: boolean } | null;
}

/** 이 키 입력이 어떤 전역 동작인가. 아무것도 아니면 null.
 *
 * `Esc` 는 입력 중에도 살린다 — 팔레트 자체가 입력을 품고 있어서, 입력 중이라고
 * 무시하면 팔레트를 키보드로 닫을 수 없다. 나머지는 입력 중이면 전부 양보한다.
 */
export function resolveShortcut(event: ShortcutEventLike): ShortcutAction {
  if (event.key === "Escape") return "close";

  const typing = isTypingTarget(event.target ?? null);
  const cmdOrCtrl = Boolean(event.metaKey || event.ctrlKey);

  // ⌘K 는 입력 중에도 연다 — 팔레트를 여는 동작에 modifier 가 붙어 있어 평범한
  // 타이핑과 충돌하지 않고, 브라우저 기본 동작(검색)을 가로채는 것이 의도다.
  if (cmdOrCtrl && event.key.toLowerCase() === "k") return "palette";

  if (typing) return null;
  if (cmdOrCtrl || event.altKey) return null;

  if (event.key === "?") return "help";
  return null;
}
