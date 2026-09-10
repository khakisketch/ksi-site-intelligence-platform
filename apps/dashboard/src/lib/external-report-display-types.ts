/**
 * A display-only pairing that has been re-bound to the exact retained report
 * subjects. These values originate in Core responses; callers must not derive
 * or reconstruct either opaque reference.
 */
export type ExactSafeDerivative = {
  role: "baseline" | "current";
  workOrderId: string;
  submissionRef: string;
  revision: number;
  sanitizedDisplayRef: string;
  receiptDigest: string;
  capturedFrom: string;
  capturedTo: string;
};

export type ExactReportSafeDerivativePair =
  | {
    state: "READY";
    baseline: ExactSafeDerivative;
    current: ExactSafeDerivative;
  }
  | {
    state: "UNAVAILABLE";
    reason: string;
  };
