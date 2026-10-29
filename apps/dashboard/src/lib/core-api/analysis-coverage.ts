import "server-only";

import { createHash } from "node:crypto";
import { MAX_COVERAGE_BYTES, coverageFitsDisplay, decodeAnalysisCoverage, coverageMatchesSummary, isCoverageGridReference,
  type AnalysisCoverageResource, type AnalysisCoverageWire } from "../analysis-coverage";
import { getAnalysis, getAnalysisEvidence } from "./analysis";
import { CoreApiError } from "./client";
import { coreApiBaseUrl } from "./env";
import { getSessionToken } from "./session";

function invalid(): never { throw new CoreApiError(502, { detail: "ANALYSIS_COVERAGE_INVALID" }); }
function changed(): never { throw new CoreApiError(409, { detail: "ANALYSIS_SNAPSHOT_CHANGED" }); }

async function readBytes(response: Response, maximum: number): Promise<Uint8Array> {
  if (!response.body) return invalid();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > maximum) { await reader.cancel(); return invalid(); }
      chunks.push(next.value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}

/** The browser supplies no upstream URL, range, token or output size. Core checks every slice. */
export async function getAnalysisCoverage(siteId: string, analysisId: string, signal?: AbortSignal): Promise<AnalysisCoverageResource> {
  if (![siteId, analysisId].every((value) => /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$/.test(value))) {
    throw new CoreApiError(400, { detail: "INVALID_IDENTIFIER" });
  }
  const timeout = AbortSignal.timeout(20_000);
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  try {
    requestSignal.throwIfAborted();
    const before = await getAnalysis(siteId, analysisId, { signal: requestSignal });
    if (before.siteId !== siteId || before.analysisId !== analysisId || before.executionState !== "COMPLETED"
      || !before.result || !["PROVISIONAL_ACCURACY_UNVERIFIED", "EVALUATED"].includes(before.suitabilityState)) {
      throw new CoreApiError(404, { detail: "ANALYSIS_NOT_FOUND" });
    }
    const summary = before.result.coverage;
    if (!coverageFitsDisplay(summary.rows, summary.columns)) {
      throw new CoreApiError(413, { detail: "ANALYSIS_COVERAGE_DISPLAY_LIMIT" });
    }
    const token = await getSessionToken();
    const upstream = new URL(`/v2/sites/${encodeURIComponent(siteId)}/analyses/${encodeURIComponent(analysisId)}/coverage`, `${coreApiBaseUrl()}/`);
    let total = 0, digest = "";
    const range = async (start: number, end: number): Promise<Uint8Array> => {
      const response = await fetch(upstream.toString(), { cache: "no-store", redirect: "error", signal: requestSignal,
        headers: { Authorization: `Bearer ${token}`, Range: `bytes=${start}-${end}` } });
      if (response.status !== 206) {
        await response.body?.cancel();
        // Do not relay arbitrary upstream bodies, redirects, or headers.
        if ([401, 403, 404, 409, 503].includes(response.status)) throw new CoreApiError(response.status, {});
        return invalid();
      }
      const match = /^bytes (\d{1,9})-(\d{1,9})\/(\d{1,9})$/.exec(response.headers.get("content-range") ?? "");
      const length = end - start + 1;
      const nextTotal = match ? Number(match[3]) : 0;
      const nextDigest = response.headers.get("x-ksi-coverage-digest") ?? "";
      if (!match || Number(match[1]) !== start || Number(match[2]) !== end || nextTotal <= end
        || nextTotal > MAX_COVERAGE_BYTES || response.headers.get("content-length") !== String(length)
        || response.headers.get("x-ksi-coverage-total-length") !== String(nextTotal)
        || !/^sha256:[0-9a-f]{64}$/.test(nextDigest)
        || response.headers.get("content-type")?.split(";")[0] !== "application/vnd.ksi.analysis-coverage+json"
        || total && (nextTotal !== total || nextDigest !== digest)) {
        await response.body?.cancel(); return invalid();
      }
      total = nextTotal; digest = nextDigest;
      const bytes = await readBytes(response, length);
      if (bytes.length !== length) return invalid();
      return bytes;
    };
    const first = await range(0, 0);
    const payload = new Uint8Array(total); payload.set(first);
    for (let start = 1; start < total; start += 65_536) {
      payload.set(await range(start, Math.min(total - 1, start + 65_535)), start);
    }
    if (`sha256:${createHash("sha256").update(payload).digest("hex")}` !== digest) return invalid();
    let wire: AnalysisCoverageWire;
    try {
      wire = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(payload));
      decodeAnalysisCoverage(wire);
    } catch { return invalid(); }
    if (wire.contractVersion !== "external-relative-volume-coverage-witness.v2" || !coverageMatchesSummary(wire, summary)
      || wire.coverageWitnessDigest === null && digest !== summary.coverageWitnessDigest) return invalid();
    const evidence = await getAnalysisEvidence(siteId, analysisId, { limit: 32, signal: requestSignal });
    if (evidence.analysisId !== analysisId || evidence.evidenceDigest !== before.evidenceDigest) return changed();
    const baseline = evidence.items.find((item) => item.kind === "EPOCH_IDENTITY" && item.epoch === "BASELINE"
      && item.selector.workOrderId === before.baseline.workOrderId && item.selector.submissionRef === before.baseline.submissionRef
      && item.selector.revision === before.baseline.revision);
    const reference = baseline?.kind === "EPOCH_IDENTITY"
      ? { observedCrsIdentifier: baseline.observedCrsIdentifier, transform: baseline.transform } : null;
    // Missing/unsupported location evidence does not erase the exact grid view or invent a CRS.
    const gridReference = reference && isCoverageGridReference(reference, wire) ? reference : null;
    // A completed result may become unavailable between slices; never publish mixed/stale masks.
    const after = await getAnalysis(siteId, analysisId, { signal: requestSignal });
    if (after.siteId !== siteId || after.analysisId !== analysisId || after.workAreaId !== before.workAreaId
      || after.executionState !== "COMPLETED" || after.suitabilityState !== before.suitabilityState
      || after.evidenceDigest !== before.evidenceDigest || !after.result
      || after.result.resultId !== before.result.resultId || after.result.reportDigest !== before.result.reportDigest
      || after.result.numericResultIdentityDigest !== before.result.numericResultIdentityDigest
      || after.result.coverage.coverageWitnessDigest !== summary.coverageWitnessDigest) return changed();
    return { siteId, analysisId, workAreaId: before.workAreaId, resultId: before.result.resultId,
      reportDigest: before.result.reportDigest, numericResultIdentityDigest: before.result.numericResultIdentityDigest, coverage: wire, gridReference };
  } catch (error) {
    if (requestSignal.aborted) throw new CoreApiError(504, { detail: "ANALYSIS_COVERAGE_TIMEOUT" });
    throw error;
  }
}
