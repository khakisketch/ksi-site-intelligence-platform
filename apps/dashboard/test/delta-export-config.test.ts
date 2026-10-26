import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
import { resolveDeltaExportDeliveryConfig } from "@/lib/delta-export-config";

afterEach(() => vi.unstubAllEnvs());

describe("explicit delta delivery settings", () => {
  it("does not guess a retention lifetime or browser byte budget", () => {
    vi.stubEnv("KSI_DASHBOARD_DELTA_EXPORT_LIFETIME_SECONDS", "");
    vi.stubEnv("KSI_DASHBOARD_DELTA_EXPORT_DOWNLOAD_BUDGET_BYTES", "");
    expect(resolveDeltaExportDeliveryConfig()).toBeNull();
  });

  it.each(["0", "-1", "true", "10.5", "1e6", " 60", "9007199254740992"])(
    "fails closed on the invalid configured value %s", (value) => {
      vi.stubEnv("KSI_DASHBOARD_DELTA_EXPORT_LIFETIME_SECONDS", value);
      vi.stubEnv("KSI_DASHBOARD_DELTA_EXPORT_DOWNLOAD_BUDGET_BYTES", "1000000");
      expect(resolveDeltaExportDeliveryConfig()).toBeNull();
    },
  );

  it("passes only the two explicit non-secret numeric settings to the result UI", () => {
    vi.stubEnv("KSI_DASHBOARD_DELTA_EXPORT_LIFETIME_SECONDS", "120");
    vi.stubEnv("KSI_DASHBOARD_DELTA_EXPORT_DOWNLOAD_BUDGET_BYTES", "1000000");
    expect(resolveDeltaExportDeliveryConfig()).toEqual({ lifetimeSeconds: 120, downloadBudgetBytes: 1000000 });
  });
});
