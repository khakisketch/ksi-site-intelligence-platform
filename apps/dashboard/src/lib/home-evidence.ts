import "server-only";

import { cache } from "react";

import { getEvent, getEvidenceViewUrl } from "@/lib/core-api/events";

export interface HomeEvidencePreview {
  src: string;
  contentType: string;
  artifactId: string;
}

/**
 * Home은 실제 등록된 사건 증거만 이미지로 사용한다. 합성 현장 사진이나 고정
 * placeholder URL을 production에 싣지 않으며, 증거가 없거나 열람 URL 발급이
 * 실패하면 null로 낮춰 명시적인 "근거 이미지 미등록" 상태를 보여 준다(INV-040).
 */
export const getHomeEventEvidencePreview = cache(
  async (eventKey: string): Promise<HomeEvidencePreview | null> => {
    const event = await getEvent(eventKey);
    const candidate = event.evidence
      .filter((artifact) => artifact.tombstonedAt === null && artifact.contentType.startsWith("image/"))
      .toSorted((a, b) => b.registeredAt.localeCompare(a.registeredAt))[0];
    if (!candidate) return null;

    const view = await getEvidenceViewUrl(eventKey, candidate.artifactId);
    return {
      src: view.viewUrl,
      contentType: view.contentType,
      artifactId: view.artifactId,
    };
  },
);
