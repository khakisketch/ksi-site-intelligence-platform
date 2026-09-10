const requestPrefix = "external-relative-volume-";
const reportPrefix = "external-relative-volume-report-";
const generatedReferenceSuffix = /^[0-9a-f]{32}$/;
const maxReferenceLength = 255;

function isGeneratedReference(value: unknown, prefix: string): value is string {
  return typeof value === "string" &&
    value.length <= maxReferenceLength &&
    value.startsWith(prefix) &&
    generatedReferenceSuffix.test(value.slice(prefix.length));
}

/** Core-generated public references are bounded in total, including the fixed prefix. */
export function isExternalRelativeVolumeRequestReference(value: unknown): value is string {
  return isGeneratedReference(value, requestPrefix);
}

/** Core-generated report references are bounded in total, including the fixed prefix. */
export function isExternalRelativeVolumeReportReference(value: unknown): value is string {
  return isGeneratedReference(value, reportPrefix);
}
