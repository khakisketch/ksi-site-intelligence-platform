export type DirectEvidenceUploadGrant = { uploadUrl: string; requiredHeaders: Record<string, string> };

/** Core binds this direct object upload to the previously declared evidence digest. */
export async function putExternalEvidenceFile(grant: DirectEvidenceUploadGrant, file: File, signal?: AbortSignal): Promise<void> {
  const response = await fetch(grant.uploadUrl, { method: "PUT", headers: grant.requiredHeaders, body: file, redirect: "error", signal });
  if (!response.ok) throw new Error(`external evidence upload failed (${response.status})`);
}
