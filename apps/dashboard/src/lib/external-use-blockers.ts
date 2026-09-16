import catalog from "./external-use-blockers.generated.json";

export type BlockerOwner = "OPERATOR" | "ADMIN" | "CUSTOMER";
export type BlockerTarget =
  | "SUBJECT"
  | "INSPECTION"
  | "DISPLAY"
  | "POLICY"
  | "EVIDENCE"
  | "MAPPING"
  | "ZONE"
  | "HEIGHT"
  | "GENERAL";

type Reason = { title: string; explanation: string; owner: BlockerOwner; target: BlockerTarget };
type Remediation = { step: string; owner: BlockerOwner; target: BlockerTarget };

const REASONS = catalog.reasons as Record<string, Reason>;
const REMEDIATIONS = catalog.remediations as Record<string, Remediation>;

export const BLOCKER_OWNER_LABEL: Record<BlockerOwner, string> = {
  OPERATOR: "운영자",
  ADMIN: "관리자",
  CUSTOMER: "고객(산출물 제공자)",
};

/** Anchor ids rendered by the external panels; unknown targets fall back to GENERAL. */
export const BLOCKER_TARGET_ANCHOR: Record<BlockerTarget, string> = {
  SUBJECT: "external-submissions",
  INSPECTION: "external-submissions",
  DISPLAY: "external-submissions",
  POLICY: "external-submissions",
  EVIDENCE: "external-evidence",
  MAPPING: "external-volume",
  ZONE: "external-volume",
  HEIGHT: "external-submissions",
  GENERAL: "external-submissions",
};

export type ExternalUseBlockerGuide = {
  known: boolean;
  title: string;
  explanation: string;
  step: string;
  owner: BlockerOwner;
  ownerLabel: string;
  target: BlockerTarget;
  codes: string[];
};

const FALLBACK_STEP = "전문가 정보의 사유 코드를 확인하고 운영자에게 문의하세요.";

/**
 * Explains a BLOCKED external-use decision from the synced catalog. The first
 * known reason wins; unknown codes never throw and stay visible as raw codes.
 */
export function explainExternalUseDecision(
  reasons: readonly string[],
  remediations: readonly string[],
): ExternalUseBlockerGuide {
  const reason = reasons.map((code) => REASONS[code]).find((item) => item !== undefined);
  const remediation = remediations
    .map((code) => REMEDIATIONS[code])
    .find((item) => item !== undefined);
  const codes = [...reasons, ...remediations];
  if (!reason) {
    const owner = remediation?.owner ?? "OPERATOR";
    return {
      known: false,
      title: "판정이 막혔습니다",
      explanation: "이 사유는 아직 안내 목록에 없습니다. 사유 코드는 전문가 정보에서 확인할 수 있습니다.",
      step: remediation?.step ?? FALLBACK_STEP,
      owner,
      ownerLabel: BLOCKER_OWNER_LABEL[owner],
      target: remediation?.target ?? "GENERAL",
      codes,
    };
  }
  const owner = remediation?.owner ?? reason.owner;
  return {
    known: true,
    title: reason.title,
    explanation: reason.explanation,
    step: remediation?.step ?? FALLBACK_STEP,
    owner,
    ownerLabel: BLOCKER_OWNER_LABEL[owner],
    target: reason.target,
    codes,
  };
}
