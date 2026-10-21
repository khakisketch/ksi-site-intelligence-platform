/**
 * 표시 창의 권한·영수증 재확인 캐시(Console 측, 계정별).
 *
 * 표시/LOD 계약 §6의 Console 측 규칙이다. 캐시는 어떤 독립 권한도
 * 만들지 않는다 — 매 사용 때 다음을 다시 확인한다.
 *
 * 1. grant가 아직 유효한지, 2. 회수 기록이 없는지, 3. 용도(purpose)가
 *    여전히 허락하는지, 4. 바이트를 준비한 주체와 같은 주체인지,
 *    5. 영수증 사실(sha/size)이 같은지.
 *
 * 하나라도 어긋나면 그 창을 더는 내놓지 않고(fail-closed) 캐시에서
 * 지운다. 다른 주체의 창은 존재를 드러내지 않는 같은 문구로 닫는다.
 * 공유 캐시는 두지 않는다 — 계정·용도별 보관만 한다.
 */

export type DisplayCachePurpose = "GENERAL_DATA_USE" | "EXTERNAL_AI";

export interface CachedDisplayWindow {
  stableKey: string;
  assetRef: string;
  pixelWindow: readonly [number, number, number, number];
  outputSha256: string;
  outputSizeBytes: number;
  grantDigest: string;
  policyDigest: string;
  purpose: DisplayCachePurpose;
  preparedForPrincipalHash: string;
  /**
   * S2 — 설계 §1.3 권리·통화·범위 핀. 현재 권리-무관 조회(`stableKey`만)로는
   * 경계를 넘나드는 조회를 막을 수 없어 키에 그대로 반복한다. 순서는
   * §3과 같다: 범위(수혜자·조직) → grant 유효 → 회수 없음 → 용도 →
   * 요청자 소유 → 영수증. grant·정책 회전은 키를 바꾸고 픽셀은 바꾸지
   * 않는다. LOD 핀은 S5(GAP-03)가 열리기 전까지 `NONE`(네이티브 잘라내기만,
   * 재표본화 없음)을 truthfully 둔다 — LOD 값을 지어내지 않는다.
   */
  beneficiaryPrincipalId: string;
  organizationId: string;
  allowedBoundsDigest: string;
  observedCrsDigest: string;
  grantRevision: string;
  policyRevision: string;
  activationDigest: string;
  tileSize: number;
  lodTableVersion: string;
  kernelId: string;
}

export interface DisplayRightsRecheck {
  grantLive: boolean;
  notRevoked: boolean;
  purposeAllowed: boolean;
  samePrincipal: boolean;
  receiptMatches: boolean;
}

export type DisplayCacheRefusal =
  | "GRANT_EXPIRED"
  | "REVOKED"
  | "PURPOSE_MISMATCH"
  | "FOREIGN_PRINCIPAL"
  | "RECEIPT_CHANGED";

export type DisplayCacheServeResult =
  | { ok: true; entry: CachedDisplayWindow }
  | { ok: false; reason: DisplayCacheRefusal };

export const DISPLAY_CACHE_REFUSAL_COPY: Record<DisplayCacheRefusal, string> = {
  GRANT_EXPIRED: "창을 볼 권한의 유효 기간이 지나 이 창을 더는 표시하지 않습니다. 담당자에게 권한 확인을 요청하세요.",
  REVOKED: "창을 볼 권한이 회수되어 이 창을 더는 표시하지 않습니다. 담당자에게 권한 확인을 요청하세요.",
  PURPOSE_MISMATCH: "이 창의 사용 용도가 달라 표시하지 않습니다. 용도에 맞는 창을 새로 요청하세요.",
  FOREIGN_PRINCIPAL:
    "요청을 찾을 수 없거나 현재 조회할 수 없습니다. 다른 계정이 준비한 창은 이 화면에서 열 수 없습니다.",
  RECEIPT_CHANGED: "받은 바이트가 Core 준비 기록과 달라 화면에 표시하지 않습니다.",
};

function cacheSlot(entry: CachedDisplayWindow): string {
  return [
    entry.stableKey,
    entry.grantDigest,
    entry.policyDigest,
    entry.purpose,
    entry.preparedForPrincipalHash,
    entry.beneficiaryPrincipalId,
    entry.organizationId,
    entry.allowedBoundsDigest,
    entry.observedCrsDigest,
    entry.grantRevision,
    entry.policyRevision,
    entry.activationDigest,
    String(entry.tileSize),
    entry.lodTableVersion,
    entry.kernelId,
  ].join("|");
}

/**
 * 계정·용도별 보관 — 호출자가 주체 해시를 바르게 넣어야 하며, 이
 * 캐시는 해시를 만들거나 검증하지 않는다. 같은 주체의 같은 슬롯만
 * 맞댄다.
 */
export class DisplayWindowCache {
  private readonly slots = new Map<string, CachedDisplayWindow>();

  store(entry: CachedDisplayWindow): void {
    this.slots.set(cacheSlot(entry), entry);
  }

  /**
   * 매 사용 때 권리·영수증을 다시 확인한다. 실패하면 보관분을 지우고
   * 내놓지 않는다 — 만료·회수된 창을 캐시에서 계속 내놓지 않는다.
   */
  serve(entry: CachedDisplayWindow, recheck: DisplayRightsRecheck): DisplayCacheServeResult {
    if (!recheck.samePrincipal) {
      this.slots.delete(cacheSlot(entry));
      return { ok: false, reason: "FOREIGN_PRINCIPAL" };
    }
    if (!recheck.grantLive) {
      this.slots.delete(cacheSlot(entry));
      return { ok: false, reason: "GRANT_EXPIRED" };
    }
    if (!recheck.notRevoked) {
      this.slots.delete(cacheSlot(entry));
      return { ok: false, reason: "REVOKED" };
    }
    if (!recheck.purposeAllowed) {
      this.slots.delete(cacheSlot(entry));
      return { ok: false, reason: "PURPOSE_MISMATCH" };
    }
    if (!recheck.receiptMatches) {
      this.slots.delete(cacheSlot(entry));
      return { ok: false, reason: "RECEIPT_CHANGED" };
    }
    const stored = this.slots.get(cacheSlot(entry));
    if (!stored) return { ok: false, reason: "RECEIPT_CHANGED" };
    if (
      stored.outputSha256 !== entry.outputSha256 ||
      stored.outputSizeBytes !== entry.outputSizeBytes
    ) {
      this.slots.delete(cacheSlot(entry));
      return { ok: false, reason: "RECEIPT_CHANGED" };
    }
    return { ok: true, entry: stored };
  }

  invalidate(entry: CachedDisplayWindow): void {
    this.slots.delete(cacheSlot(entry));
  }

  clear(): void {
    this.slots.clear();
  }

  get size(): number {
    return this.slots.size;
  }
}
