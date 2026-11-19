import { isUploadGrantView } from "@/lib/external-submission-echo";

export type DirectUploadGrant = {
  artifactId: string;
  uploadUrl: string;
  requiredHeaders: Record<string, string>;
};

export type SealObservationFailureCode = "OBSERVATION_MISSING" | "OBSERVATION_MISMATCH";

/** The seal BFF exposes these two Core verdicts as exact `code` values on 422. */
export function sealObservationFailureCode(status: number, payload: unknown): SealObservationFailureCode | null {
  if (status !== 422 || !payload || typeof payload !== "object") return null;
  const code = (payload as { code?: unknown }).code;
  return code === "OBSERVATION_MISSING" || code === "OBSERVATION_MISMATCH" ? code : null;
}

export function sealObservationFailureMessage(code: SealObservationFailureCode): string {
  const reason = code === "OBSERVATION_MISSING"
    ? "서버 저장소에서 업로드한 파일을 찾지 못해 제출을 봉인하지 못했습니다."
    : "서버 저장소의 파일 내용이 제출 정보와 맞지 않아 제출을 봉인하지 못했습니다.";
  return `${reason} 같은 제출로 다시 시도하면 이 제출의 파일을 모두 다시 올립니다.`;
}

/** Select one capability only after confirming that this response covers the full submitted revision. */
export function selectCompleteUploadGrant(
  payload: unknown,
  expectedArtifactIds: readonly string[],
  artifactId: string,
): DirectUploadGrant | null {
  if (!expectedArtifactIds.includes(artifactId) || new Set(expectedArtifactIds).size !== expectedArtifactIds.length) return null;
  const value = payload && typeof payload === "object" ? payload as { grants?: unknown } : null;
  if (!value || !Array.isArray(value.grants) || !value.grants.every(isUploadGrantView)) return null;
  const ids = value.grants.map((grant) => grant.artifactId);
  if (new Set(ids).size !== ids.length || ids.length !== expectedArtifactIds.length || !expectedArtifactIds.every((id) => ids.includes(id))) return null;
  return value.grants.find((grant) => grant.artifactId === artifactId) ?? null;
}

/** Upload directly to the Core-issued object URL. The file never crosses the BFF. */
export async function putExternalReconstructionFile(
  grant: DirectUploadGrant,
  file: File,
  signal?: AbortSignal,
  onVerifiedBytes?: (transferredBytes: number) => void,
): Promise<void> {
  // Fetch does not expose incremental request-body progress. Report only byte counts
  // that this client knows: no bytes confirmed before the request, then the whole
  // file after the Core-issued upload URL accepts it. This keeps redirect rejection
  // and direct-upload semantics rather than replacing the request with a weaker XHR.
  onVerifiedBytes?.(0);
  const response = await fetch(grant.uploadUrl, {
    method: "PUT",
    headers: grant.requiredHeaders,
    body: file,
    redirect: "error",
    signal,
  });
  if (!response.ok) throw new Error(`external artifact upload failed (${response.status})`);
  onVerifiedBytes?.(file.size);
}
