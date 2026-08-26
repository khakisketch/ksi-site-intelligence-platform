"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { useMutation } from "@/hooks/useMutation";
import type { MissionExecutionStatus, MissionExecutionView } from "@/lib/core-api/types";

/**
 * 미리 보여줄 거부 사유. `CANCELLED` 는 "이미 전달됨"과 다른 사실이다 — 취소된
 * 임무는 애초에 날려선 안 되는 것이지, 늦게 눌러서 거부되는 게 아니다. 둘을 같은
 * 문장으로 뭉개면 조종자가 "취소됐다"를 "누군가 이미 처리했다"로 오해할 수 있다.
 * null 이면 경고를 보여주지 않는다(ISSUED 이거나 상태를 아직 모름).
 */
export function manualDispatchRejectionWarning(
  executionStatus: MissionExecutionStatus | null,
): string | null {
  if (executionStatus === null || executionStatus === "ISSUED") return null;
  if (executionStatus === "CANCELLED") {
    return "취소된 임무입니다 — 비행해서는 안 됩니다.";
  }
  return "이미 전달이 확인된 임무라 서버가 거부할 수 있습니다.";
}

/**
 * [수동 이관 신고] — 자동 전달(ADR-KSI-019 G1)이 확인되지 않는 동안, KMZ 를 직접
 * 조종기로 옮긴 사람이 "내가 기체로 넘겼다"는 사실을 서버에 남긴다.
 *
 * **신규 서버 API 가 아니다.** mission_execution.py 의 execution-transitions
 * 엔드포인트(대상 DISPATCHED, MISSIONS_ISSUE 권한)를 그대로 부른다 — 이미 사람이
 * 선언할 수 있는 상태로 정의돼 있었는데(_HUMAN_DECLARABLE), 현장 화면에 그걸 부르는
 * 버튼이 없었을 뿐이다.
 *
 * `DISPATCHED` 는 서버 전이표(_ALLOWED_MISSION_EXECUTION_TRANSITIONS)에서
 * `ISSUED` 에서만 나간다 — 이미 전달이 확인된 임무에서 누르면 서버가 409 로
 * 거부한다. 그래도 버튼을 감추지 않는다: 이 화면은 실패를 감지해야 나타나는
 * 컨트롤을 만들지 않는다(page.tsx 상단 설계 주석과 같은 원칙) — 상태를 잘못 안
 * 순간에는 버튼이 아니라 서버 응답이 사실을 말하게 둔다.
 */
export function ManualDispatchButton({
  missionId,
  canDeclare,
  executionStatus,
}: {
  missionId: string;
  /** MISSIONS_ISSUE 보유 여부 — 없으면 버튼 대신 이유를 보여준다(SourceUploadPanel 과 같은 패턴). */
  canDeclare: boolean;
  /** null 이면 실행 상태 표면을 아직 모른다 — 그래도 신고 자체는 시도할 수 있게 둔다. */
  executionStatus: MissionExecutionStatus | null;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const { mutate, errorMessage } = useMutation<MissionExecutionView>();

  if (!canDeclare) {
    return (
      <p className="text-[12px] break-keep text-ink-muted">
        수동 이관을 신고하려면 임무 발급 권한(MISSIONS_ISSUE)이 필요합니다.
      </p>
    );
  }

  // 이미 전달이 확인됐거나 취소된 뒤라는 걸 알면 미리 알려준다 — 눌러도 되지만
  // (버튼을 지우지 않는다는 원칙), 왜 거부될 수 있는지·왜 눌러선 안 되는지
  // 누르기 전에 말해 둔다.
  const rejectionWarning = manualDispatchRejectionWarning(executionStatus);

  async function handleClick() {
    setPending(true);
    setDone(false);
    await mutate(
      `/api/missions/${encodeURIComponent(missionId)}/execution-transitions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targetStatus: "DISPATCHED" }),
      },
      () => {
        setDone(true);
        router.refresh();
      },
    );
    setPending(false);
  }

  return (
    <div className="flex flex-col items-start gap-1.5">
      <button
        type="button"
        onClick={() => void handleClick()}
        disabled={pending}
        className="btn"
      >
        {pending ? "신고 중…" : "수동 이관 신고"}
      </button>
      <p className="text-[12px] break-keep text-ink-2">
        KMZ 를 직접 조종기로 옮겼다면 눌러서 서버에 남기세요.
        {rejectionWarning && ` ${rejectionWarning}`}
      </p>
      {done && !errorMessage && (
        <p role="status" className="text-[12px] break-keep text-safe-ink">
          신고했습니다 — 위 배지가 갱신됐습니다.
        </p>
      )}
      {errorMessage && (
        <p role="alert" className="text-[12px] font-semibold break-keep text-crit-ink">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
