import type { Tone } from "@/lib/core-api/labels";
import type { AcquisitionProgressView, AcquisitionReadinessView } from "@/lib/core-api/types";

export interface AcquisitionStatusRow {
  label: string;
  value: string;
  tone: Tone;
}

export interface AcquisitionReadinessPresentation {
  label: string;
  detail: string;
  tone: Tone;
  rows: AcquisitionStatusRow[];
}

const SYNC_LABEL = {
  NOT_STARTED: { value: "시작 전", tone: "neutral" },
  PENDING: { value: "동기화 중", tone: "progress" },
  ACTIVATED: { value: "활성화 확인", tone: "positive" },
  COMPLETE: { value: "완료", tone: "positive" },
  FAILED: { value: "실패", tone: "warning" },
} as const;

export function presentAcquisitionReadiness(
  readiness: AcquisitionReadinessView | null,
  progress: AcquisitionProgressView | null = null,
): AcquisitionReadinessPresentation {
  if (!readiness) {
    return {
      label: "연결 상태 확인 불가",
      detail: "장비 준비 상태를 확인하지 못했습니다. 새 비행 임무를 발급하지 마세요.",
      tone: "warning",
      rows: unavailableRows(),
    };
  }

  const snapshot = readiness.connectivity;
  const directEnabled = readiness.profile?.manifoldDirectMode === "CONNECTIVITY_ADD_ON";
  const contract = progress
    ? contractProgressLabel(progress.contractActivation.state)
    : snapshot
      ? SYNC_LABEL[snapshot.missionContractSync]
      : null;
  const media = progress
    ? mediaProgressLabel(progress.media.state)
    : snapshot
      ? SYNC_LABEL[snapshot.rawMediaSync]
      : null;
  const activeContractOffline =
    progress?.contractActivation.state === "ACTIVATED" && !readiness.readyForMissionIssue;
  const detail = readiness.readyForMissionIssue
    ? "RC 인터넷과 필요한 장비 기능이 확인됐습니다. 새 비행 임무를 준비할 수 있습니다."
    : activeContractOffline
      ? "새 비행 임무를 발급하려면 연결 확인이 필요하지만, 이미 활성화된 계약은 계속 유효합니다."
    : (readiness.reasons[0] ?? "새 비행 임무 발급 조건을 아직 확인하지 못했습니다.");

  return {
    label: readiness.readyForMissionIssue
      ? "새 비행 임무 발급 가능"
      : activeContractOffline
        ? "활성 계약 유지 · 새 비행 임무 차단"
        : "새 비행 임무 발급 차단",
    detail,
    tone: readiness.readyForMissionIssue ? "positive" : "warning",
    rows: [
      {
        label: "RC 인터넷",
        value: snapshot?.internetReachable ? `${snapshot.transport} 연결` : "연결 확인 안 됨",
        tone: snapshot?.internetReachable ? "positive" : "warning",
      },
      {
        label: "Manifold 연결",
        value: snapshot ? connectionLabel(snapshot.edgeState) : "확인 안 됨",
        tone: snapshot?.edgeState === "CONNECTED" ? "positive" : "warning",
      },
      {
        label: "직접망 Add-on",
        value: directEnabled
          ? snapshot
            ? connectionLabel(snapshot.directEdgeState)
            : "확인 안 됨"
          : "사용 안 함",
        tone:
          !directEnabled || snapshot?.directEdgeState === "CONNECTED" ? "neutral" : "caution",
      },
      {
        label: "계약 동기화",
        value: contract?.value ?? "확인 안 됨",
        tone: contract?.tone ?? "neutral",
      },
      {
        label: "원본 동기화",
        value: media?.value ?? "확인 안 됨",
        tone: media?.tone ?? "neutral",
      },
    ],
  };
}

function contractProgressLabel(
  state: AcquisitionProgressView["contractActivation"]["state"],
): { value: string; tone: Tone } {
  if (state === "ACTIVATED") return { value: "활성화 확인", tone: "positive" };
  if (state === "PENDING") return { value: "활성화 대기", tone: "progress" };
  return { value: "시작 전", tone: "neutral" };
}

function mediaProgressLabel(
  state: AcquisitionProgressView["media"]["state"],
): { value: string; tone: Tone } {
  if (state === "VERIFIED") return { value: "검증 완료", tone: "positive" };
  if (state === "VERIFYING") return { value: "검증 중", tone: "progress" };
  if (state === "SYNCING") return { value: "동기화 중", tone: "progress" };
  return { value: "시작 전", tone: "neutral" };
}

function connectionLabel(state: "CONNECTED" | "DISCONNECTED" | "UNKNOWN" | "DISABLED"): string {
  switch (state) {
    case "CONNECTED":
      return "연결됨";
    case "DISCONNECTED":
      return "연결 끊김";
    case "DISABLED":
      return "사용 안 함";
    case "UNKNOWN":
      return "확인 안 됨";
  }
}

function unavailableRows(): AcquisitionStatusRow[] {
  return ["RC 인터넷", "Manifold 연결", "직접망 Add-on", "계약 동기화", "원본 동기화"].map(
    (label) => ({ label, value: "확인 안 됨", tone: "neutral" }),
  );
}
