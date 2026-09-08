import "server-only";

import { coreFetch } from "./client";
import type { ExternalSubmissionCandidate } from "../external-reconstruction-submission";

export type ExternalRevisionView = {
  submissionRef: string;
  submission: ExternalSubmissionCandidate;
  state: "REGISTERED" | "SEALED";
  manifest: unknown | null;
};

export type ExternalUploadGrant = {
  artifactId: "ortho" | "dsm";
  objectKey: string;
  uploadUrl: string;
  requiredHeaders: Record<string, string>;
};

const base = (workOrderId: string) =>
  `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions`;

export async function listExternalReconstructionSubmissions(workOrderId: string): Promise<ExternalRevisionView[]> {
  return (await coreFetch<{ submissions: ExternalRevisionView[] }>(base(workOrderId))).submissions;
}

export function registerExternalReconstructionSubmission(
  workOrderId: string,
  submission: ExternalSubmissionCandidate,
): Promise<ExternalRevisionView> {
  return coreFetch(base(workOrderId), { method: "POST", body: submission });
}

export async function requestExternalReconstructionUploadGrants(
  workOrderId: string,
  submissionRef: string,
  revision: number,
): Promise<ExternalUploadGrant[]> {
  const path = `${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/upload-grants`;
  return (await coreFetch<{ grants: ExternalUploadGrant[] }>(path, { method: "POST" })).grants;
}

export function sealExternalReconstructionSubmission(
  workOrderId: string,
  submissionRef: string,
  revision: number,
): Promise<ExternalRevisionView> {
  return coreFetch(`${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/seal`, { method: "POST" });
}
