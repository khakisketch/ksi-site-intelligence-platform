import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";

export type ExternalInspectionPresentation = {
  title: string;
  detail: string;
  nextAction: string;
  artifactReasons: string[];
  /** Only these GET projections may receive the panel's bounded automatic refresh. */
  autoRefresh: boolean;
  displayReady: boolean;
};

function artifactLabel(artifactId: string): string {
  if (artifactId === "ortho") return "정사영상";
  if (artifactId === "dsm") return "DSM";
  return `산출물 ${artifactId}`;
}

function presentOutcomeReason(reason: string): string {
  const known: Record<string, string> = {
    ARTIFACT_MISSING: "선언된 파일을 찾을 수 없습니다.",
    DECLARED_BYTES_MISSING: "선언된 파일 바이트를 확인할 수 없습니다.",
    UNSUPPORTED_FORMAT: "지원하지 않는 파일 형식입니다.",
    MISSING_CRS: "좌표계 선언이 없습니다.",
    VALIDATION_INCOMPLETE: "검증을 완료할 수 없습니다.",
  };
  if (known[reason]) return known[reason];
  return /^[A-Z][A-Z0-9_]*$/.test(reason)
    ? "추가 확인이 필요합니다. 파일 정보 · 처리 상세의 사유 코드를 확인하세요."
    : reason;
}

function outcomeReasons(view: ExternalArtifactInspectionView): string[] {
  if (!Array.isArray(view.inspection.outcome)) return [];
  return view.inspection.outcome.flatMap((item) => (
    typeof item?.artifactId === "string" && typeof item.reason === "string" && item.reason.trim()
      ? [`${artifactLabel(item.artifactId)}: ${presentOutcomeReason(item.reason)}`]
      : []
  ));
}

function presentation(
  title: string,
  detail: string,
  nextAction: string,
  options: Pick<ExternalInspectionPresentation, "autoRefresh" | "displayReady">,
  artifactReasons: string[] = [],
): ExternalInspectionPresentation {
  return { title, detail, nextAction, artifactReasons, ...options };
}

/**
 * This projection intentionally makes no processing or readiness inference.
 * It translates only retained registration, inspection, display, and artifact outcome facts.
 */
export function presentExternalInspectionStatus(view: ExternalArtifactInspectionView): ExternalInspectionPresentation {
  if (view.registrationState === "REGISTERED" || view.sealState === "UNSEALED" || view.inspection.state === "INSPECTION_PENDING_SEAL") {
    return presentation(
      "자료 등록됨 · 파일 제출 마무리 필요",
      "파일 저장과 제출 마무리가 확인되기 전에는 검사와 표시 준비가 시작되지 않습니다.",
      "등록 이어하기로 같은 파일의 업로드와 제출 마무리를 완료하세요.",
      { autoRefresh: false, displayReady: false },
      outcomeReasons(view),
    );
  }

  switch (view.inspection.state) {
    case "INSPECTION_PENDING_POLICY":
      return presentation(
        "검사 기준 확인 필요",
        "이 봉인 파일에 적용할 검사 기준이 아직 준비되지 않았습니다.",
        "관리자에게 검사 설정 확인을 요청하세요. 필요하면 상태를 새로고침하세요.",
        { autoRefresh: false, displayReady: false },
      );
    case "INSPECTION_PENDING":
      return presentation(
        "파일 검사 준비 중",
        "봉인된 파일의 검사 요청이 준비되고 있습니다.",
        "검사 요청이 대기열에 들어갈 때까지 기다리거나 상태를 새로고침하세요.",
        { autoRefresh: true, displayReady: false },
      );
    case "INSPECTION_QUEUED":
      return presentation(
        "파일 검사 대기열",
        "검사 작업이 대기열에 있습니다. 아직 파일 형식이나 측정 적합성은 확인되지 않았습니다.",
        "대기열이 처리될 때까지 기다리거나 상태를 새로고침하세요.",
        { autoRefresh: true, displayReady: false },
      );
    case "INSPECTION_RUNNING":
      return presentation(
        "파일 검사 중",
        "봉인된 산출물을 검사하고 있습니다. 이 상태는 업로드 재시도를 뜻하지 않습니다.",
        "검사가 끝날 때까지 기다리거나 상태를 새로고침하세요.",
        { autoRefresh: true, displayReady: false },
      );
    case "INSPECTION_FAILED_INCOMPLETE":
      return presentation(
        "파일 검사 불완료",
        "검사 보고가 완결되지 않았습니다. 수치나 정제 표시를 준비된 것으로 표시하지 않습니다.",
        outcomeReasons(view).length > 0
          ? "아래 산출물별 사유를 확인한 뒤 필요한 파일 또는 선언을 보완하세요."
          : "완결된 사유가 아직 제공되지 않았습니다. 상태를 새로고침하고 계속되면 관리자에게 문의하세요.",
        { autoRefresh: false, displayReady: false },
        outcomeReasons(view),
      );
    case "INSPECTION_REPORTED":
      break;
    default:
      return presentation(
        "검사 상태를 확인할 수 없음",
        "현재 검사 또는 표시 상태를 해석할 수 없습니다. 준비 완료로 추정하지 않습니다.",
        "상태를 새로고침하고 계속되면 파일 정보 · 처리 상세와 함께 운영자에게 문의하세요.",
        { autoRefresh: false, displayReady: false },
        outcomeReasons(view),
      );
  }

  switch (view.display.state) {
    case "PENDING_INSPECTION":
    case "PENDING_POLICY":
      return presentation(
        "검사 보고 완료 · 정제 표시 준비 대기",
        "파일 검사 보고는 기록됐지만 정제 정사영상 표시 준비가 아직 시작되지 않았습니다.",
        "표시 준비 상태를 새로고침하세요. 이 화면은 원본 산출물을 열지 않습니다.",
        { autoRefresh: true, displayReady: false },
        outcomeReasons(view),
      );
    case "NOT_REQUIRED":
      return presentation(
        "검사 보고 완료 · 정제 표시 미발급",
        "현재 결과에는 정제 정사영상 표시가 발급되지 않았습니다.",
        "검사 보고는 확인할 수 있지만 원본 또는 대체 표시를 만들지 않습니다.",
        { autoRefresh: false, displayReady: false },
        outcomeReasons(view),
      );
    case "QUEUED":
      return presentation(
        "정제 정사영상 준비 대기열",
        "검사 보고는 완료됐고 안전한 표시 파생본 생성이 대기열에 있습니다.",
        "대기열이 처리될 때까지 기다리거나 상태를 새로고침하세요.",
        { autoRefresh: true, displayReady: false },
        outcomeReasons(view),
      );
    case "RUNNING":
      return presentation(
        "정제 정사영상 준비 중",
        "검사 보고에 결속된 안전한 표시 파생본을 만들고 있습니다.",
        "준비가 끝날 때까지 기다리거나 상태를 새로고침하세요.",
        { autoRefresh: true, displayReady: false },
        outcomeReasons(view),
      );
    case "RETRY_EXHAUSTED":
      return presentation(
        "정제 정사영상 준비 실패",
        "검사 보고는 남아 있지만 안전한 표시 파생본을 현재 발급할 수 없습니다.",
        "상태를 새로고침해 현재 보관 사실을 확인하세요. 원본 표시나 성공 상태로 바꾸지 않습니다.",
        { autoRefresh: false, displayReady: false },
        outcomeReasons(view),
      );
    case "SEALED":
      if (typeof view.display.sanitizedDisplayRef === "string" && typeof view.display.receiptDigest === "string") {
        return presentation(
          "정제 정사영상 표시 가능",
          "검사 보고와 현재 표시 영수증에 결속된 파생본만 열 수 있습니다.",
          "정제 정사영상을 열어 현재 표시 권한을 다시 확인하세요.",
          { autoRefresh: false, displayReady: true },
          outcomeReasons(view),
        );
      }
      return presentation(
        "정제 표시 영수증 확인 필요",
        "표시 상태는 봉인으로 기록됐지만 현재 표시 식별자 또는 영수증이 없습니다.",
        "상태를 새로고침해 현재 표시 영수증을 확인하세요.",
        { autoRefresh: false, displayReady: false },
        outcomeReasons(view),
      );
    default:
      return presentation(
        "검사 상태를 확인할 수 없음",
        "현재 검사 또는 표시 상태를 해석할 수 없습니다. 준비 완료로 추정하지 않습니다.",
        "상태를 새로고침하고 계속되면 파일 정보 · 처리 상세와 함께 운영자에게 문의하세요.",
        { autoRefresh: false, displayReady: false },
        outcomeReasons(view),
      );
  }
}
