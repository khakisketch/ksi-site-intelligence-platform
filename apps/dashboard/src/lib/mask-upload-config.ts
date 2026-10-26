import "server-only";

export type MaskUploadConfig = {
  /** 마스크 원시 업로드 섭취 상한(바이트) — 서버 설정에서만 온다. */
  uploadBudgetBytes: number;
};

/**
 * 마스크 업로드 명시적 서버 예산. Core 자원 외피
 * (`ResourceEnvelopeV1.max_input_bytes`/`max_streamed_bytes`)가 최종
 * 상한이며, 이 값은 BFF 섭취 bound일 뿐 발명된 기본값이 아니다.
 * 설정이 없으면 업로드를 막는다(`null` — 조용히 기본값으로 두지 않는다).
 */
export function resolveMaskUploadConfig(): MaskUploadConfig | null {
  const raw = process.env.KSI_DASHBOARD_MASK_UPLOAD_BUDGET_BYTES;
  if (!raw || !/^[1-9]\d*$/.test(raw)) return null;
  const budget = Number(raw);
  if (!Number.isSafeInteger(budget)) return null;
  return { uploadBudgetBytes: budget };
}
