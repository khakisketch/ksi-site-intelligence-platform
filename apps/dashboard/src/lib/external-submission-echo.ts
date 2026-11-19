import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";
import { registrationInstantMicros } from "@/lib/registration-history";
import type {
  ExternalArtifactKind,
  ExternalV3CaptureBasis,
  ExternalV3ProducerKnowledge,
  ExternalV3RetentionLocus,
} from "@/lib/external-reconstruction-submission";

/**
 * 외부 산출물 등록 응답이 "이번 시도의 응답인가"를 대조하는 순수 함수 모음.
 * 등록 화면(ExternalReconstructionPanel)과 한 화면 올리기가 같은 대조를 쓰도록 한 곳에 둔다.
 * 동작은 패널에 있던 때와 같다.
 */
export type ArtifactDeclaration = { artifactId: ExternalArtifactKind; kind: ExternalArtifactKind; fileName: string; format: "GeoTIFF"; contentType: "application/octet-stream"; declaredSha256: string; declaredSizeBytes: number; declaredCrs: string | null; declaredVerticalReference: null; declaredGsdM: null };
export type RevisionSubmission = {
  submissionId?: string; revision: number; observationEpochId?: string;
  contractVersion?: string;
  producerDeclaration?: { softwareName?: string | null; softwareVersion?: string | null; producerKnowledge?: string | null; sourceNote?: string | null };
  inputDeclaration?: {
    captureBasis?: string | null; captureDate?: string | null; captureStartedAt?: string | null; captureEndedAt?: string | null;
    originalRetentionLocus?: string | null; originalRetentionDetail?: string | null;
    upstreamSource?: { sourceUri?: string | null; sourceSha256?: string | null; licenceDeclaration?: string | null; retrievalNote?: string | null } | null;
    derivativeExport?: { toolName?: string | null; toolVersion?: string | null; settingsDigest?: string | null; exportedAt?: string | null; exportNote?: string | null } | null;
  } | null;
  submittedAt?: string;
  // 유지 기록의 산출물 식별자는 Core 계약상 자유 문자열이다(제출 내 유일).
  // V1/V2에는 kind와 다른 artifact_id나 ortho/dsm 외 종류가 올 수 있으므로
  // `"ortho" | "dsm"` 리터럴로 좁히지 않는다. 화면의 두 슬롯은 재개 대상을
  // 고르는 용도이며, 실제 grant 결속은 아래 bindings의 artifactId로 한다.
  artifacts?: { artifactId: string; kind: string; fileName: string; declaredSha256: string; declaredSizeBytes: number }[];
};
export type Revision = { submissionRef: string; submission: RevisionSubmission; state: "REGISTERED" | "SEALED" };
export type V3DeclarationBody = {
  submissionId: string; expectedEpochId: string; submittedAt: string;
  correctionOf?: { submissionRef: string; revision: number };
  producerKnowledge: ExternalV3ProducerKnowledge; softwareName: string | null; softwareVersion: string | null; sourceNote: string | null;
  captureBasis: ExternalV3CaptureBasis; captureStartedAt: string | null; captureEndedAt: string | null; captureDate: string | null;
  originalRetentionLocus: ExternalV3RetentionLocus; originalRetentionDetail: string | null;
  upstreamSource: { sourceUri: string; sourceSha256: string | null; licenceDeclaration: string | null; retrievalNote: string | null } | null;
  derivativeExport: { toolName: string; toolVersion: string; settingsDigest: string | null; exportedAt: string | null; exportNote: string | null } | null;
  artifacts: readonly ArtifactDeclaration[];
};

export const SUBMISSION_REF_PATTERN = /^ers-v1-[0-9a-f]{64}$/;
export const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

export type EchoArtifact = {
  artifactId: string;
  kind: string;
  declaredSha256: string;
  declaredSizeBytes: number;
  fileName: string;
  declaredCrs: string | null;
};

export type DeclarationEcho = {
  submissionId: string;
  revision: number;
  observationEpochId: string;
  submittedAt: unknown;
  artifacts: readonly EchoArtifact[];
  producer: {
    knowledge: unknown;
    softwareName: unknown;
    softwareVersion: unknown;
    sourceNote: unknown;
  };
  input: {
    captureBasis: unknown;
    captureStartedAt: unknown;
    captureEndedAt: unknown;
    captureDate: unknown;
    retentionLocus: unknown;
    retentionDetail: unknown;
    upstream: unknown;
    derivative: unknown;
  };
};

export type AttemptEcho = DeclarationEcho & {
  // 신규 등록 응답의 ref는 서버가 새로 발급하므로 형식만 본다. 봉인 응답은
  // 요청 경로에 쓴 ref와 정확히 같아야 한다.
  submissionRef: string | null;
  // A corrected revision reuses the prior stream's opaque ref. This hint lets
  // declarationEchoOfRequest bind it without changing existing call-site shapes.
  expectedSubmissionRef?: string | null;
};

export type RequestDeclarationEcho = DeclarationEcho & { expectedSubmissionRef: string | null };

export function isAbsent(value: unknown): value is null | undefined {
  return value === null || value === undefined;
}

// null과 undefined는 같은 부재로 본다(V1/V2 기록에 없는 블록 대응).
// 나머지는 문자열 그대로 대조한다.
export function sameText(a: unknown, b: unknown): boolean {
  if (isAbsent(a) || isAbsent(b)) return isAbsent(a) && isAbsent(b);
  return typeof a === "string" && typeof b === "string" && a === b;
}

// Core가 datetime으로 보관했다가 ISO로 돌려주므로 Z/+00:00 표기 차이를
// 순간 비교로 흡수한다. 둘 다 nullish면 같고, 한쪽만이면 다르다. 파싱
// 불가도 불일치로 둔다.
export function sameInstant(a: unknown, b: unknown): boolean {
  if (isAbsent(a) || isAbsent(b)) return isAbsent(a) && isAbsent(b);
  const ta = registrationInstantMicros(a);
  return ta !== null && ta === registrationInstantMicros(b);
}

export function sameUpstream(a: unknown, b: unknown): boolean {
  if (isAbsent(a) || isAbsent(b)) return isAbsent(a) && isAbsent(b);
  if (typeof a !== "object" || typeof b !== "object") return false;
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  return sameText(left.sourceUri, right.sourceUri)
    && sameText(left.sourceSha256, right.sourceSha256)
    && sameText(left.licenceDeclaration, right.licenceDeclaration)
    && sameText(left.retrievalNote, right.retrievalNote);
}

export function sameDerivative(a: unknown, b: unknown): boolean {
  if (isAbsent(a) || isAbsent(b)) return isAbsent(a) && isAbsent(b);
  if (typeof a !== "object" || typeof b !== "object") return false;
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  return sameText(left.toolName, right.toolName)
    && sameText(left.toolVersion, right.toolVersion)
    && sameText(left.settingsDigest, right.settingsDigest)
    && sameInstant(left.exportedAt, right.exportedAt)
    && sameText(left.exportNote, right.exportNote);
}

export function echoArtifactsMatch(echoArtifacts: unknown, expected: DeclarationEcho["artifacts"]): boolean {
  // 집합이 정확히 일치해야 한다 — 일부만 맞거나 여분·누락·복제가 있으면 안
  // 된다. Core가 결속하는 모양과 같은 것만 받는다: artifact_id 키 집합이
  // 정확히 같고, 각 항목의 종류·선언 해시·크기·파일명·좌표계가 같다.
  // artifactId===kind는 V3 BFF 신규 등록 본문 검증일 뿐, 선언·관측 계약이나
  // Core 결속(V1/V2 포함)의 범용 제약이 아니므로 요구하지 않는다.
  if (!Array.isArray(echoArtifacts)) return false;
  if (echoArtifacts.length !== expected.length) return false;
  const expectedById = new Map(expected.map((item) => [item.artifactId, item]));
  if (expectedById.size !== expected.length) return false;
  const seen = new Set<string>();
  return echoArtifacts.every((item) => {
    if (!item || typeof item !== "object") return false;
    const candidate = item as Record<string, unknown>;
    if (typeof candidate.artifactId !== "string" || typeof candidate.kind !== "string") return false;
    if (seen.has(candidate.artifactId)) return false;
    seen.add(candidate.artifactId);
    const matched = expectedById.get(candidate.artifactId);
    return matched !== undefined &&
      candidate.kind === matched.kind &&
      candidate.declaredSha256 === matched.declaredSha256 &&
      candidate.declaredSizeBytes === matched.declaredSizeBytes &&
      candidate.fileName === matched.fileName &&
      candidate.declaredCrs === matched.declaredCrs;
  });
}

export function echoDeclarationBlocksMatch(submission: unknown, expected: DeclarationEcho): boolean {
  // 원래 사용자 신고의 대조 가능한 값을 대조한다 — 제작자·촬영 시점·원본
  // 보관·공개 출처·파일명·좌표계. 서버 발급값(식별자·서명·관측 시각)은
  // 대조하지 않고, expected에 없는 키(V1/V2 기록)는 부재로 둔다.
  if (!submission || typeof submission !== "object") return false;
  const record = submission as Record<string, unknown>;
  const producer = record.producerDeclaration;
  if (!producer || typeof producer !== "object") return false;
  const producerRecord = producer as Record<string, unknown>;
  if (!sameText(producerRecord.producerKnowledge, expected.producer.knowledge)) return false;
  if (!sameText(producerRecord.softwareName, expected.producer.softwareName)) return false;
  if (!sameText(producerRecord.softwareVersion, expected.producer.softwareVersion)) return false;
  if (!sameText(producerRecord.sourceNote, expected.producer.sourceNote)) return false;
  const input = record.inputDeclaration;
  if (!input || typeof input !== "object") return false;
  const inputRecord = input as Record<string, unknown>;
  if (!sameText(inputRecord.captureBasis, expected.input.captureBasis)) return false;
  if (!sameInstant(inputRecord.captureStartedAt, expected.input.captureStartedAt)) return false;
  if (!sameInstant(inputRecord.captureEndedAt, expected.input.captureEndedAt)) return false;
  if (!sameText(inputRecord.captureDate, expected.input.captureDate)) return false;
  if (!sameText(inputRecord.originalRetentionLocus, expected.input.retentionLocus)) return false;
  if (!sameText(inputRecord.originalRetentionDetail, expected.input.retentionDetail)) return false;
  if (!sameUpstream(inputRecord.upstreamSource, expected.input.upstream)) return false;
  if (!sameDerivative(inputRecord.derivativeExport, expected.input.derivative)) return false;
  return sameInstant(record.submittedAt, expected.submittedAt);
}

export function echoSubmissionMatches(submission: unknown, expected: DeclarationEcho): boolean {
  if (!submission || typeof submission !== "object") return false;
  const echo = submission as Record<string, unknown>;
  if (echo.submissionId !== expected.submissionId) return false;
  if (echo.revision !== expected.revision) return false;
  if (echo.observationEpochId !== expected.observationEpochId) return false;
  if (!echoArtifactsMatch(echo.artifacts, expected.artifacts)) return false;
  return echoDeclarationBlocksMatch(submission, expected);
}

// 유지된 제출 기록에서 봉인 대조용 신원을 뽑는다. 하나라도 없으면 대조하지
// 않고 모름으로 둔다(추측으로 채우지 않는다).
export function declarationEchoOfRequest(body: V3DeclarationBody): RequestDeclarationEcho {
  // V3 등록 요청서에서 응답 대조값을 뽑는다. 수정 제출은 원래 참조값을 유지하고
  // 버전만 올린다. 나머지 선언값은 Core에 보낸 그대로 대조하며 시각은 순간으로 본다.
  return {
    expectedSubmissionRef: body.correctionOf?.submissionRef ?? null,
    submissionId: body.submissionId,
    revision: body.correctionOf ? body.correctionOf.revision + 1 : 1,
    observationEpochId: body.expectedEpochId,
    submittedAt: body.submittedAt,
    artifacts: body.artifacts.map((item) => ({
      artifactId: item.artifactId,
      kind: item.kind,
      declaredSha256: item.declaredSha256,
      declaredSizeBytes: item.declaredSizeBytes,
      fileName: item.fileName,
      declaredCrs: item.declaredCrs,
    })),
    producer: {
      knowledge: body.producerKnowledge,
      softwareName: body.softwareName,
      softwareVersion: body.softwareVersion,
      sourceNote: body.sourceNote,
    },
    input: {
      captureBasis: body.captureBasis,
      captureStartedAt: body.captureStartedAt,
      captureEndedAt: body.captureEndedAt,
      captureDate: body.captureDate,
      retentionLocus: body.originalRetentionLocus,
      retentionDetail: body.originalRetentionDetail,
      upstream: body.upstreamSource,
      derivative: body.derivativeExport,
    },
  };
}
export function retainedEchoOf(submission: unknown): DeclarationEcho | null {
  // 유지된 제출 기록에서 대조용 신원을 뽑는다. 하나라도 대조 가능한 값이
  // 아니면 모름으로 둔다(추측으로 채우지 않는다). V1/V2 기록에 없는 블록은
  // 부재로 두어 echo 쪽 부재와 일치할 때만 통과한다.
  if (!submission || typeof submission !== "object") return null;
  const record = submission as Record<string, unknown>;
  const { submissionId, revision, observationEpochId, submittedAt, artifacts, producerDeclaration, inputDeclaration } = record;
  if (typeof submissionId !== "string" || typeof revision !== "number" || typeof observationEpochId !== "string" || !Array.isArray(artifacts)) return null;
  const files: EchoArtifact[] = [];
  for (const item of artifacts) {
    if (!item || typeof item !== "object") return null;
    const candidate = item as Record<string, unknown>;
    if (typeof candidate.kind !== "string" || typeof candidate.artifactId !== "string" || typeof candidate.declaredSha256 !== "string" || typeof candidate.declaredSizeBytes !== "number") return null;
    if (typeof candidate.fileName !== "string") return null;
    if (candidate.declaredCrs !== null && candidate.declaredCrs !== undefined && typeof candidate.declaredCrs !== "string") return null;
    files.push({
      artifactId: candidate.artifactId,
      kind: candidate.kind,
      declaredSha256: candidate.declaredSha256,
      declaredSizeBytes: candidate.declaredSizeBytes,
      fileName: candidate.fileName,
      declaredCrs: typeof candidate.declaredCrs === "string" ? candidate.declaredCrs : null,
    });
  }
  const producer = producerDeclaration && typeof producerDeclaration === "object" ? (producerDeclaration as Record<string, unknown>) : null;
  if (producer === null) return null;
  const input = inputDeclaration && typeof inputDeclaration === "object" ? (inputDeclaration as Record<string, unknown>) : null;
  if (input === null) return null;
  return {
    submissionId,
    revision,
    observationEpochId,
    submittedAt: typeof submittedAt === "string" ? submittedAt : null,
    artifacts: files,
    producer: {
      knowledge: producer.producerKnowledge,
      softwareName: producer.softwareName,
      softwareVersion: producer.softwareVersion,
      sourceNote: producer.sourceNote,
    },
    input: {
      captureBasis: input.captureBasis,
      captureStartedAt: input.captureStartedAt,
      captureEndedAt: input.captureEndedAt,
      captureDate: input.captureDate,
      retentionLocus: input.originalRetentionLocus,
      retentionDetail: input.originalRetentionDetail,
      upstream: input.upstreamSource,
      derivative: input.derivativeExport,
    },
  };
}

// 등록·봉인 응답이 이번 시도(신규 동결 또는 명시적 재개)의 것인지 확인한다.
// Core revision 화면의 실제 모양만 본다 — submissionRef 모양·상태·제출 묶음·
// 버전·epoch·입력 바이트가 하나라도 다르면 성공으로 표시하지 않는다.
// 계약 버전·필드 모양을 새로 지어내지 않고, 화면에서 받은 submissionRef와
// V3 request echo의 revision을 함께 확인한다.
export function isRevisionViewForAttempt(
  value: unknown,
  expected: AttemptEcho,
  state: "REGISTERED" | "SEALED",
): value is Revision {
  if (!value || typeof value !== "object") return false;
  const view = value as Record<string, unknown>;
  if (typeof view.submissionRef !== "string" || !SUBMISSION_REF_PATTERN.test(view.submissionRef)) return false;
  const expectedRef = expected.expectedSubmissionRef ?? expected.submissionRef;
  if (expectedRef !== null && view.submissionRef !== expectedRef) return false;
  if (view.state !== state) return false;
  // Core _view가 SEALED로 적는 조건(관측 바이트 결속 보유)과 같은 것만 본다.
  // manifest 화면의 제출 묶음·버전·epoch·관측 entries 집합이 어긋나거나
  // 비어 있으면 확정하지 않는다. 서버 발급 식별자의 값 자체는 대조하지
  // 않는다. REGISTERED는 미보유여야 한다.
  if (state === "SEALED") {
    const echoRecord = view.submission;
    const echoDigest = echoRecord && typeof echoRecord === "object"
      ? (echoRecord as Record<string, unknown>).submissionDigest
      : undefined;
    // 제출 digest는 봉인된 기록에만 Core가 반드시 적는다. 계약 표면
    // (_DIGEST_PATTERN)이 아니거나 manifest와 다르면 같은 시도의 응답이
    // 아니다. 양쪽이 같은 잘못된 문자열이어도 확정하지 않는다.
    if (typeof echoDigest !== "string" || !DIGEST_PATTERN.test(echoDigest)) return false;
    if (!sealedManifestMatches(view.manifest, expected, echoDigest)) return false;
  } else if (view.manifest !== null && view.manifest !== undefined) {
    return false;
  } else {
    // Core revision 화면은 봉인 전부터 sealed 제출을 싣는다 — submissionDigest
    // 없는 REGISTERED는 계약 표면이 어긋난 것이므로 확정하지 않는다.
    const record = view.submission;
    const digest = record && typeof record === "object" ? (record as Record<string, unknown>).submissionDigest : undefined;
    if (typeof digest !== "string" || !DIGEST_PATTERN.test(digest)) return false;
  }
  return echoSubmissionMatches(view.submission, expected);
}

// 봉인 manifest 결속 대조 — Core manifest 화면의 실제 모양만 본다. 계약
// 리터럴·제출 묶음·버전·epoch은 정확히, 관측 entries는 빈틈없이 같은 집합일
// 때만 통과한다. manifest의 submissionDigest는 같은 응답의 제출 digest와
// 같아야 한다(둘 다 Core가 적는 값이며, 맞지 않으면 다른 제출의 manifest다).
// entries는 Core가 제출 산출물과 1:1로 묶는 artifact_id 기준으로 대조한다.
export function sealedManifestMatches(manifest: unknown, expected: DeclarationEcho, submissionDigest: string): boolean {
  if (!manifest || typeof manifest !== "object") return false;
  const record = manifest as Record<string, unknown>;
  if (record.contractVersion !== "external-reconstruction-manifest.v1") return false;
  if (record.submissionId !== expected.submissionId) return false;
  if (record.submissionRevision !== expected.revision) return false;
  if (record.observationEpochId !== expected.observationEpochId) return false;
  if (record.submissionDigest !== submissionDigest) return false;
  // Core는 봉인된 manifest에만 manifestDigest를 적는다 — 없거나 어긋나면
  // 같은 시도의 응답이 아니다. 값의 재계산은 하지 않고 표면만 본다.
  if (typeof record.manifestDigest !== "string" || !DIGEST_PATTERN.test(record.manifestDigest)) return false;
  const entries = record.entries;
  if (!Array.isArray(entries) || entries.length === 0) return false;
  if (entries.length !== expected.artifacts.length) return false;
  const expectedById = new Map(expected.artifacts.map((item) => [item.artifactId, item]));
  if (expectedById.size !== expected.artifacts.length) return false;
  const seen = new Set<string>();
  return entries.every((entry) => {
    if (!entry || typeof entry !== "object") return false;
    const candidate = entry as Record<string, unknown>;
    if (typeof candidate.artifactId !== "string" || typeof candidate.kind !== "string") return false;
    if (seen.has(candidate.artifactId)) return false;
    seen.add(candidate.artifactId);
    const matched = expectedById.get(candidate.artifactId);
    return matched !== undefined &&
      candidate.kind === matched.kind &&
      candidate.observedSha256 === matched.declaredSha256 &&
      candidate.observedSizeBytes === matched.declaredSizeBytes;
  });
}

export type UploadGrantView = { artifactId: string; uploadUrl: string; requiredHeaders: Record<string, string> };

// grant 응답의 화면 측 모양 — Core grant 화면의 실제 모양만 본다(대상·주소·
// 요청 헤더). 직접 PUT은 검증된 이 capability로만 내보낸다.
export function isUploadGrantView(value: unknown): value is UploadGrantView {
  if (!value || typeof value !== "object") return false;
  const grant = value as Record<string, unknown>;
  return typeof grant.artifactId === "string" &&
    typeof grant.uploadUrl === "string" && grant.uploadUrl.length > 0 &&
    !!grant.requiredHeaders && typeof grant.requiredHeaders === "object" &&
    Object.values(grant.requiredHeaders as Record<string, unknown>).every((header) => typeof header === "string");
}

export function isExternalArtifactInspectionView(value: unknown): value is ExternalArtifactInspectionView {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  const inspection = candidate.inspection;
  const display = candidate.display;
  return (candidate.registrationState === "REGISTERED" || candidate.registrationState === "SEALED") &&
    (candidate.sealState === "UNSEALED" || candidate.sealState === "SEALED") &&
    !!inspection && typeof inspection === "object" && typeof (inspection as Record<string, unknown>).state === "string" &&
    !!display && typeof display === "object" && typeof (display as Record<string, unknown>).state === "string";
}

