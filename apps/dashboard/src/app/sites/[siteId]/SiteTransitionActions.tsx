"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import type { SiteStatus } from "@/lib/core-api/types";

// 서버 SSOT: packages/domain/src/ksi_domain/enums.py _ALLOWED_SITE_TRANSITIONS
// (MASTER_PRD §6.3/§6.1). 이 표가 낡아도 안전하게 실패한다 — 서버가 최종 검증하므로
// 여기선 도달 불가능한 선택지를 숨기는 용도뿐이다(EventActions.tsx 와 같은 패턴).
const ALLOWED_SITE_TRANSITIONS: Record<SiteStatus, SiteStatus[]> = {
  UNMAPPED: ["BASELINE_MAPPING", "SUSPENDED"],
  BASELINE_MAPPING: ["MODEL_PROCESSING", "SUSPENDED"],
  MODEL_PROCESSING: ["MODEL_VALIDATION", "SUSPENDED"],
  MODEL_VALIDATION: ["PROVISIONAL_AUTONOMY", "REMAP_REQUIRED", "SUSPENDED"],
  PROVISIONAL_AUTONOMY: ["PATROL_READY", "REMAP_REQUIRED", "SUSPENDED"],
  PATROL_READY: ["PATROL_ACTIVE", "MODEL_STALE", "SUSPENDED"],
  PATROL_ACTIVE: ["PATROL_READY", "MODEL_STALE", "SUSPENDED"],
  MODEL_STALE: ["MODEL_PROCESSING", "REMAP_REQUIRED", "SUSPENDED"],
  REMAP_REQUIRED: ["BASELINE_MAPPING", "SUSPENDED"],
  SUSPENDED: [],
};

export function SiteTransitionActions({
  siteId,
  status,
  resumeTarget,
}: {
  siteId: string;
  status: SiteStatus;
  resumeTarget: SiteStatus | null;
}) {
  const router = useRouter();
  const [targetStatus, setTargetStatus] = useState<SiteStatus | "">("");
  const [evidence, setEvidence] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // SUSPENDED 는 저장소가 기억한 진입 직전 상태로만 복귀한다(동적 규칙 — 정적 표에
  // 없다). 그 외 상태는 정적 표를 그대로 쓴다.
  const allowedTargets: SiteStatus[] =
    status === "SUSPENDED"
      ? resumeTarget
        ? [resumeTarget]
        : []
      : ALLOWED_SITE_TRANSITIONS[status];

  async function submit() {
    if (!targetStatus) return;
    setPending(true);
    setErrorMessage(null);
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/transitions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targetStatus, evidence, reason }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        setErrorMessage(
          (payload && typeof payload.message === "string" && payload.message) ||
            "요청을 처리하지 못했습니다.",
        );
        return;
      }
      setEvidence("");
      setReason("");
      setTargetStatus("");
      router.refresh();
    } catch {
      setErrorMessage("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    } finally {
      setPending(false);
    }
  }

  if (allowedTargets.length === 0) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
        <h2 className="text-[13.5px] font-bold break-keep">상태 전이</h2>
        <p className="text-[12.5px] break-keep text-ink-muted">
          현재 상태({SITE_STATUS_LABEL[status].label})에서 전이할 수 있는 상태가 없습니다.
        </p>
      </div>
    );
  }

  const canSubmit =
    Boolean(targetStatus) && evidence.trim().length > 0 && reason.trim().length > 0 && !pending;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <h2 className="text-[13.5px] font-bold break-keep">상태 전이</h2>
      <label className="flex flex-col gap-1 text-[12.5px]">
        <span className="break-keep text-ink-2">다음 상태</span>
        <select
          className="input"
          value={targetStatus}
          onChange={(e) => setTargetStatus(e.target.value as SiteStatus)}
        >
          <option value="">선택하세요</option>
          {allowedTargets.map((s) => (
            <option key={s} value={s}>
              {SITE_STATUS_LABEL[s].label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[12.5px]">
        <span className="break-keep text-ink-2">근거 (필수)</span>
        <textarea
          className="input"
          rows={2}
          value={evidence}
          onChange={(e) => setEvidence(e.target.value)}
          placeholder="전이 근거 — 비워두면 제출할 수 없습니다."
        />
      </label>
      <label className="flex flex-col gap-1 text-[12.5px]">
        <span className="break-keep text-ink-2">사유 (필수)</span>
        <textarea
          className="input"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="전이 사유 — 비워두면 제출할 수 없습니다."
        />
      </label>
      <button
        type="button"
        className="btn btn-primary"
        disabled={!canSubmit}
        onClick={submit}
      >
        {pending ? "처리 중…" : "상태 전이"}
      </button>
      {errorMessage && (
        <p role="alert" className="break-keep text-[12.5px] text-crit-ink">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
