import type { AnalysisEvidencePage, AnalysisView } from "@/lib/core-api/analysis";

/** A selected Core AP identity is evidence, not V2 numeric success or V3 authority. */
export function boundMaskedSourceIdentity(
  detail: AnalysisView,
  pages: readonly AnalysisEvidencePage[],
): string | null {
  if (pages.length === 0 || pages.some((page) => page.analysisId !== detail.analysisId
    || page.evidenceRevision !== detail.evidenceRevision || page.evidenceDigest !== detail.evidenceDigest)) return null;
  const identities = new Set<string>();
  for (const page of pages) {
    for (const item of page.items) {
      if (item.kind !== "AUTHORITY_REFERENCE" || item.referenceName !== "calculationIdentityDigest") continue;
      if (typeof item.sourceDigest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(item.sourceDigest)) return null;
      identities.add(item.sourceDigest);
    }
  }
  return identities.size === 1 ? [...identities][0]! : null;
}
