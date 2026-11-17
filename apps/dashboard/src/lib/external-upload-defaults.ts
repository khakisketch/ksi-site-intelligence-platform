/**
 * 등록할 때마다 같은 제작 소프트웨어를 다시 쓰지 않도록, 마지막으로 등록한 소프트웨어 이름·버전을 이 브라우저에만 기억한다.
 * 신고 값일 뿐이며 서버로 보내지 않는다. 기억 값은 빈 칸을 채우는 데만 쓰고 입력한 값이나 파일 헤더 값을 덮지 않는다.
 * 원본 보관 위치·촬영 시점처럼 등록마다 사실이 달라질 수 있는 신고는 기억하지 않는다(추정 금지).
 * 저장소를 못 쓰는 환경(사생활 보호 창, 차단)에서는 조용히 기억 없이 동작한다.
 */

export type ExternalUploadDefaults = {
  softwareName: string;
  softwareVersion: string;
};

const KEY = "ksi.external-upload-defaults.v1";
const MAX_TEXT = 255;

function text(value: unknown): string {
  return typeof value === "string" ? value.trim().slice(0, MAX_TEXT) : "";
}

export function parseExternalUploadDefaults(raw: string | null): ExternalUploadDefaults | null {
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const record = value as Record<string, unknown>;
    const softwareName = text(record.softwareName);
    return softwareName ? { softwareName, softwareVersion: text(record.softwareVersion) } : null;
  } catch {
    return null;
  }
}

export function loadExternalUploadDefaults(): ExternalUploadDefaults | null {
  try {
    return parseExternalUploadDefaults(window.localStorage.getItem(KEY));
  } catch {
    return null;
  }
}

export function saveExternalUploadDefaults(defaults: ExternalUploadDefaults): void {
  try {
    const softwareName = text(defaults.softwareName);
    if (!softwareName) return;
    window.localStorage.setItem(KEY, JSON.stringify({ softwareName, softwareVersion: text(defaults.softwareVersion) }));
  } catch {
    // 저장하지 못해도 등록은 그대로 진행한다.
  }
}
