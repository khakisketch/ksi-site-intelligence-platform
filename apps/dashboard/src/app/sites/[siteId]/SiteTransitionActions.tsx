"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useMutation } from "@/hooks/useMutation";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { requiresAutonomyApproval } from "@/lib/core-api/siteAutonomyGate";
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
  canApproveAutonomy,
}: {
  siteId: string;
  status: SiteStatus;
  resumeTarget: SiteStatus | null;
  /** SITES_AUTONOMY_APPROVE 보유 여부 — 관리자 전용 간선을 선택지에 보일지 결정한다. */
  canApproveAutonomy: boolean;
}) {
  const router = useRouter();
  const [targetStatus, setTargetStatus] = useState<SiteStatus | "">("");
  const [evidence, setEvidence] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const { mutate, errorMessage } = useMutation();

  // SUSPENDED 는 저장소가 기억한 진입 직전 상태로만 복귀한다(동적 규칙 — 정적 표에
  // 없다). 그 외 상태는 정적 표를 그대로 쓴다.
  const reachableTargets: SiteStatus[] =
    status === "SUSPENDED"
      ? resumeTarget
        ? [resumeTarget]
        : []
      : ALLOWED_SITE_TRANSITIONS[status];

  // 자율승인 권한이 없으면 관리자 전용 간선(현재 상태 → 이 목적지)을 선택지에서
  // 뺀다(ADR-KSI-015 D2) — 서버 403 을 마지막에 만나게 하지 않는다. **간선 쌍
  // 기준**이라 같은 PATROL_READY 목적지라도 PATROL_ACTIVE 발 순찰 복귀는 가려지지
  // 않는다(requiresAutonomyApproval 참조 — 목적지만 보면 이 회귀가 생긴다).
  const allowedTargets = canApproveAutonomy
    ? reachableTargets
    : reachableTargets.filter((nxt) => !requiresAutonomyApproval(status, nxt));
  const hiddenByAutonomyGate = reachableTargets.length - allowedTargets.length;

  async function submit() {
    if (!targetStatus) return;
    setPending(true);
    await mutate(
      `/api/sites/${encodeURIComponent(siteId)}/transitions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targetStatus, evidence, reason }),
      },
      () => {
        setEvidence("");
        setReason("");
        setTargetStatus("");
        router.refresh();
      },
    );
    setPending(false);
  }

  if (allowedTargets.length === 0) {
    // 가능한 전이가 아예 없는 것과, 있지만 전부 관리자 전용이라 가려진 것은 다른
    // 사유다 — 조용히 같은 문구로 뭉개지 않는다("가려진 선택지가 있으면 왜 안
    // 되는지 한 줄로 보여준다").
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
        <h2 className="text-[13.5px] font-bold break-keep">상태 전이</h2>
        <p className="text-[12.5px] break-keep text-ink-muted">
          {hiddenByAutonomyGate > 0
            ? "현재 상태에서 가능한 전이는 자율운영 승인 권한(관리자 전용)이 있어야 할 수 있습니다."
            : `현재 상태(${SITE_STATUS_LABEL[status].label})에서 전이할 수 있는 상태가 없습니다.`}
        </p>
      </div>
    );
  }

  const canSubmit =
    Boolean(targetStatus) && evidence.trim().length > 0 && reason.trim().length > 0 && !pending;

  return (
    <ResponsiveActionBoundary
      action="SITE_DEVICE_TRANSITION"
      reason="Site 상태 전이는 영향 범위와 근거를 함께 확인할 수 있는 노트북에서 수행합니다."
    >
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
      {hiddenByAutonomyGate > 0 && (
        <p className="break-keep text-[11.5px] text-ink-muted">
          자율운영 승인은 관리자만 할 수 있습니다 — 관리자 전용 전이 대상은 목록에서
          뺐습니다.
        </p>
      )}
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
    </ResponsiveActionBoundary>
  );
}
