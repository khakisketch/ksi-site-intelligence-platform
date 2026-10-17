/**
 * 외부 산출물 등록 파일 이름 사전 검사 — 표현·안내만 담당한다.
 *
 * 계약 원본은 Core 스키마(`packages/event-contracts/.../external_reconstruction.py`):
 * `_BASENAME_PATTERN = ^[A-Za-z0-9][A-Za-z0-9_.-]*$`, 길이 1–255. 이 모듈은 그
 * 계약을 그대로 옮긴다. 판정·재계산을 하지 않고, 원본 파일을 바꾸거나 자동으로
 * 고치지 않으며, Core 계약을 넓히지도 않는다.
 */

export const EXTERNAL_BASENAME_MAX_LENGTH = 255;

const BASENAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

/** 계약상 쓸 수 있는 이름이면 true. */
export function isSupportedExternalBasename(fileName: string): boolean {
  return describeExternalBasenameIssue(fileName) === null;
}

/**
 * 쓸 수 없는 이름이면 화면에 그대로 둘 수 있는 사유, 쓸 수 있으면 null.
 * 빈값·255자 초과·앞자리·금지 문자를 계약 순서대로 가른다.
 */
export function describeExternalBasenameIssue(fileName: string): string | null {
  if (fileName.length === 0) return "파일 이름이 비어 있습니다.";
  if (fileName.length > EXTERNAL_BASENAME_MAX_LENGTH) {
    return `파일 이름이 ${EXTERNAL_BASENAME_MAX_LENGTH}자를 넘습니다.`;
  }
  if (fileName.includes("/") || fileName.includes("\\")) return "폴더 구분자(/ \\)는 파일 이름에 사용할 수 없습니다.";
  if (/\s/.test(fileName)) return "공백은 파일 이름에 사용할 수 없습니다.";
  if (/[^\x00-\x7F]/.test(fileName)) return "한글 등 영문 외 문자는 파일 이름에 사용할 수 없습니다.";
  if (!/^[A-Za-z0-9]/.test(fileName)) return "파일 이름은 영문·숫자로 시작해야 합니다.";
  if (!BASENAME_PATTERN.test(fileName)) return "영문·숫자·밑줄(_)·점(.)·하이픈(-)만 파일 이름에 사용할 수 있습니다.";
  return null;
}
