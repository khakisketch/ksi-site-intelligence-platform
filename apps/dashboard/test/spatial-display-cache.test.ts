import { describe, expect, it } from "vitest";

import {
  DisplayWindowCache,
  DISPLAY_CACHE_REFUSAL_COPY,
  type CachedDisplayWindow,
  type DisplayRightsRecheck,
} from "@/lib/spatial-display-cache";
import { FOREIGN_WINDOW_COPY } from "@/lib/site-windowed-pixel-viewer";

const PRINCIPAL_A = `sha256:${"a".repeat(64)}`;
const PRINCIPAL_B = `sha256:${"b".repeat(64)}`;
const GRANT = `sha256:${"c".repeat(64)}`;
const POLICY = `sha256:${"d".repeat(64)}`;

function cached(overrides: Partial<CachedDisplayWindow> = {}): CachedDisplayWindow {
  return {
    stableKey: `ksa-v1-${"e".repeat(64)}|0,512,0,512|GENERAL_DATA_USE`,
    assetRef: `ksa-v1-${"e".repeat(64)}`,
    pixelWindow: [0, 512, 0, 512],
    outputSha256: `sha256:${"f".repeat(64)}`,
    outputSizeBytes: 474427,
    grantDigest: GRANT,
    policyDigest: POLICY,
    purpose: "GENERAL_DATA_USE",
    preparedForPrincipalHash: PRINCIPAL_A,
    ...overrides,
  };
}

const LIVE: DisplayRightsRecheck = {
  grantLive: true,
  notRevoked: true,
  purposeAllowed: true,
  samePrincipal: true,
  receiptMatches: true,
};

describe("DisplayWindowCache", () => {
  it("serves a live window only after re-verifying receipt facts", () => {
    const cache = new DisplayWindowCache();
    cache.store(cached());
    const served = cache.serve(cached(), LIVE);
    expect(served.ok).toBe(true);
  });

  it("stops serving an expired grant and drops it from the cache", () => {
    const cache = new DisplayWindowCache();
    cache.store(cached());
    const served = cache.serve(cached(), { ...LIVE, grantLive: false });
    expect(served).toEqual({ ok: false, reason: "GRANT_EXPIRED" });
    expect(cache.size).toBe(0);
    // 지워졌으므로 다음 사용도 내놓지 않는다.
    expect(cache.serve(cached(), LIVE).ok).toBe(false);
  });

  it("stops serving a revoked window", () => {
    const cache = new DisplayWindowCache();
    cache.store(cached());
    expect(cache.serve(cached(), { ...LIVE, notRevoked: false })).toEqual({
      ok: false,
      reason: "REVOKED",
    });
    expect(cache.size).toBe(0);
  });

  it("refuses another principal's window without widening ownership", () => {
    const cache = new DisplayWindowCache();
    cache.store(cached());
    const served = cache.serve(cached(), { ...LIVE, samePrincipal: false });
    expect(served).toEqual({ ok: false, reason: "FOREIGN_PRINCIPAL" });
    // 다른 주체에게는 존재를 드러내지 않는 같은 문구다.
    expect(DISPLAY_CACHE_REFUSAL_COPY.FOREIGN_PRINCIPAL).toBe(FOREIGN_WINDOW_COPY);
  });

  it("stops serving when receipt facts no longer match", () => {
    const cache = new DisplayWindowCache();
    cache.store(cached());
    expect(cache.serve(cached(), { ...LIVE, receiptMatches: false })).toEqual({
      ok: false,
      reason: "RECEIPT_CHANGED",
    });
    expect(cache.size).toBe(0);
  });

  it("refuses a changed purpose", () => {
    const cache = new DisplayWindowCache();
    cache.store(cached());
    expect(cache.serve(cached(), { ...LIVE, purposeAllowed: false })).toEqual({
      ok: false,
      reason: "PURPOSE_MISMATCH",
    });
  });

  it("keeps another principal's slot separate", () => {
    const cache = new DisplayWindowCache();
    cache.store(cached());
    cache.store(cached({ preparedForPrincipalHash: PRINCIPAL_B }));
    expect(cache.size).toBe(2);
    cache.serve(cached(), { ...LIVE, grantLive: false });
    // A의 슬롯만 지워지고 B의 슬롯은 남는다.
    expect(cache.size).toBe(1);
  });
});
