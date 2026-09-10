export type DirectUploadGrant = {
  artifactId: string;
  uploadUrl: string;
  requiredHeaders: Record<string, string>;
};

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
