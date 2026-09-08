export type DirectUploadGrant = {
  artifactId: string;
  uploadUrl: string;
  requiredHeaders: Record<string, string>;
};

/** Upload directly to the Core-issued object URL. The file never crosses the BFF. */
export async function putExternalReconstructionFile(grant: DirectUploadGrant, file: File, signal?: AbortSignal): Promise<void> {
  const response = await fetch(grant.uploadUrl, {
    method: "PUT",
    headers: grant.requiredHeaders,
    body: file,
    redirect: "error",
    signal,
  });
  if (!response.ok) throw new Error(`external artifact upload failed (${response.status})`);
}
