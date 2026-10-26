import "server-only";

export type DeltaExportDeliveryConfig = {
  lifetimeSeconds: number;
  downloadBudgetBytes: number;
};

/** Explicit delivery settings, not permission, activation or invented retention. */
export function resolveDeltaExportDeliveryConfig(): DeltaExportDeliveryConfig | null {
  const parse = (value: string | undefined): number | null => {
    if (!value || !/^[1-9]\d*$/.test(value)) return null;
    const number = Number(value);
    return Number.isSafeInteger(number) ? number : null;
  };
  const lifetimeSeconds = parse(process.env.KSI_DASHBOARD_DELTA_EXPORT_LIFETIME_SECONDS);
  const downloadBudgetBytes = parse(process.env.KSI_DASHBOARD_DELTA_EXPORT_DOWNLOAD_BUDGET_BYTES);
  return lifetimeSeconds !== null && downloadBudgetBytes !== null
    ? { lifetimeSeconds, downloadBudgetBytes }
    : null;
}
