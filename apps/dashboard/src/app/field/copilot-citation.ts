import type { CopilotCitationView } from "@/lib/core-api/types";

const SAFE_ID = /^[A-Za-z0-9._:-]+$/;

/**
 * Core API 경로를 브라우저가 실제로 열 수 있는 Dashboard 경로로만 변환한다.
 * 임의의 sourcePath를 href로 신뢰하지 않는다. 새 근거 유형은 명시적으로 추가한다.
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
