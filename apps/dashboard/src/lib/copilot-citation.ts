import type { CopilotCitationView } from "@/lib/core-api/types";

const SAFE_ID = /^[A-Za-z0-9._:-]+$/;

/**
 * Core의 근거 경로를 실제 Operations Console 화면으로만 변환한다.
 * sourcePath는 모델이 임의 링크를 만들 수 있는 값이 아니며, 명시한 리소스 외에는
 * 링크로 렌더하지 않는다.
 */
export function copilotCitationHref(citation: CopilotCitationView): string | null {
  const parts = citation.sourcePath.split("/");
  if (parts.length < 4 || parts[1] !== "v1") return null;

  const resource = parts[2];
  const id = parts[3];
  if (!id || id === "." || id === ".." || !SAFE_ID.test(id)) return null;
  const encodedId = encodeURIComponent(id);

  if (resource === "sites") return `/sites/${encodedId}`;
  if (resource === "missions") return `/missions/${encodedId}`;
  if (resource === "events") return `/events/${encodedId}`;
  if (resource === "observation-work-orders") {
    return `/field/work-orders/${encodedId}`;
  }
  return null;
}
