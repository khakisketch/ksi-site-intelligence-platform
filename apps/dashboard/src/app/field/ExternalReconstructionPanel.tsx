"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { FilePickerField } from "@/components/ui/FilePickerField";
import { ExternalSanitizedOrthophoto } from "@/app/field/ExternalSanitizedOrthophoto";
import { ExternalEvidencePanel } from "@/app/field/ExternalEvidencePanel";
import { presentExternalInspectionStatus } from "@/app/field/external-reconstruction-status";
import {
  ExternalResultWorkflowPanel,
  type ExternalRelativeVolumeDecision,
  type TrustedExternalResultLink,
} from "@/app/field/ExternalResultWorkflowPanel";
import { putExternalReconstructionFile } from "@/lib/external-reconstruction-upload";
import { describeExternalBasenameIssue } from "@/lib/external-reconstruction-basename";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatNumberKo } from "@/lib/number-format";
import { formatRegistrationVersion, describeArtifactKinds, submissionStateLabel, describeProducerLine, describeCaptureLine, describeRetentionLine, formatPublisherCalendarDate } from "@/app/field/registration-language";
import { ExternalHeaderRecognition, type HeaderRecognitionState } from "@/app/field/ExternalHeaderRecognition";
import { readGeoTiffHeader, recognizeGeoTiffHeader } from "@/lib/geo/geotiff-header";
import {
  seoulDateTimeLocalToUtc,
  describeV3MetadataIssue,
  isPublisherCalendarDate,
  type ExternalArtifactKind,
  type ExternalV3CaptureBasis,
  type ExternalV3ProducerKnowledge,
  type ExternalV3RetentionLocus,
} from "@/lib/external-reconstruction-submission";
import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";

type HashResult = { file: File; sha256: string; size: number };
type ArtifactDeclaration = { artifactId: ExternalArtifactKind; kind: ExternalArtifactKind; fileName: string; format: "GeoTIFF"; contentType: "application/octet-stream"; declaredSha256: string; declaredSizeBytes: number; declaredCrs: string | null; declaredVerticalReference: null; declaredGsdM: null };
type RevisionSubmission = {
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
type Revision = { submissionRef: string; submission: RevisionSubmission; state: "REGISTERED" | "SEALED" };
// bindings의 artifactId는 grant가 결속하는 저장된 산출물 식별자다. 신규 V3
// 동결에서는 BFF가 artifactId===kind를 강제하므로 slot과 같고, 재개에서는
// 유지된 제출 기록의 artifact_id를 그대로 싣는다(V1/V2의 사용자 정의 ID 대응).
type FrozenAttempt = { requestBody: Readonly<V3DeclarationBody>; bindings: readonly { slot: ExternalArtifactKind; artifactId: string; value: HashResult }[]; continuity: string };
type V3DeclarationBody = {
  submissionId: string; expectedEpochId: string; submittedAt: string;
  producerKnowledge: ExternalV3ProducerKnowledge; softwareName: string | null; softwareVersion: string | null; sourceNote: string | null;
  captureBasis: ExternalV3CaptureBasis; captureStartedAt: string | null; captureEndedAt: string | null; captureDate: string | null;
  originalRetentionLocus: ExternalV3RetentionLocus; originalRetentionDetail: string | null;
  upstreamSource: { sourceUri: string; sourceSha256: string | null; licenceDeclaration: string | null; retrievalNote: string | null } | null;
  derivativeExport: { toolName: string; toolVersion: string; settingsDigest: string | null; exportedAt: string | null; exportNote: string | null } | null;
  artifacts: readonly ArtifactDeclaration[];
};
type InspectionLoad =
  | { phase: "loading" | "error"; previous: ExternalArtifactInspectionView | null }
  | { phase: "ready"; view: ExternalArtifactInspectionView };
type UploadProgress = { artifactId: ExternalArtifactKind; transferredBytes: number; totalBytes: number; phase: "uploading" | "uploaded" };

const AUTO_INSPECTION_REFRESH_DELAY_MS = 5_000;
const AUTO_INSPECTION_REFRESH_BUDGET = 6;

function retainedInspectionView(load: InspectionLoad | undefined): ExternalArtifactInspectionView | null {
  return load?.phase === "ready" ? load.view : load?.previous ?? null;
}

function utcSeconds(): string { return new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); }
function attemptId(): string { return `console-${crypto.randomUUID()}`; }
function formatFileSize(size: number): string {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${formatNumberKo(size / (1024 * 1024), 1)} MB`;
}
function abortError(): DOMException { return new DOMException("Operation was aborted", "AbortError"); }
function isAbortError(error: unknown): boolean { return error instanceof DOMException && error.name === "AbortError"; }

function inspectionKey(revision: Revision): string { return `${revision.submissionRef}:${revision.submission.revision}`; }

// 서버 확인 계정 비교값의 화면 측 형식 검사 — 관측 등록 폼과 같은 모양만
// 받는다. BFF 비교 보조일 뿐 권한이 아니며, 헤더 없는 기존 호출자의 보호를
// 주장하는 데 쓰지 않는다.
const CONTINUITY_FINGERPRINT_PATTERN = /^v1-[0-9a-f]{64}(?![\s\S])/;
// 서버 전용 모듈을 클라이언트에 들여오지 않으므로 같은 문자열을 둔다.
const CONTINUITY_FINGERPRINT_HEADER = "x-ksi-continuity-fingerprint";
// BFF 계정 연속성 거부 코드 — 관측 등록 폼과 같은 값만 비교한다.
const ACCOUNT_CONTINUITY_MISMATCH = "ACCOUNT_CONTINUITY_MISMATCH";
// Core revision 주소의 화면 측 모양 — 목록·상세 진입이 이미 쓰는 패턴과 같다.
// Core 계약의 digest 표면(_DIGEST_PATTERN): submissionDigest·manifestDigest는
// sealed 기록에만 적히며 항상 `sha256:` + 64 hex다. 없거나 어긋나면 같은
// 시도의 응답이 아니므로 모름으로 둔다(값 자체의 재계산·인가는 하지 않는다).
const SUBMISSION_REF_PATTERN = /^ers-v1-[0-9a-f]{64}$/;
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

function responseCode(value: unknown): string {
  return value && typeof value === "object" && "code" in value
    ? String((value as { code?: unknown }).code ?? "")
    : "";
}

// 계정이 바뀌어 같은 요청을 다시 보내지 않을 때의 안내 — 원래 시도·파일·키는
// 그대로 두고 같은 화면의 같은 시도로 돌아오게 한다. 중복 방지나 권한 판정을
// 주장하지 않는다.
function accountMismatchMessage(): string {
  return "계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력·파일 선택은 이 화면에 그대로 있습니다. 다른 탭에서 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 시도로 다시 시도하세요. 먼저 목록에서 같은 제출이 있는지 확인하세요. 새로고침하면 입력·파일 선택·동결된 요청이 사라집니다.";
}

// 응답을 확인하지 못했을 때의 안내 — 서버 접수 유무를 확정하지 않고 같은
// 시도의 복구(같은 식별자 재확인·목록 확인)로 남긴다.
function unknownResponseMessage(): string {
  return "응답을 확인하지 못했습니다. 같은 시도는 같은 식별자로 다시 확인할 수 있으니 목록에서 실제 상태를 먼저 확인하세요.";
}

type EchoArtifact = {
  artifactId: string;
  kind: string;
  declaredSha256: string;
  declaredSizeBytes: number;
  fileName: string;
  declaredCrs: string | null;
};

type DeclarationEcho = {
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

type AttemptEcho = DeclarationEcho & {
  // 신규 등록 응답의 ref는 서버가 새로 발급하므로 형식만 본다. 봉인 응답은
  // 요청 경로에 쓴 ref와 정확히 같아야 한다.
  submissionRef: string | null;
};

function isAbsent(value: unknown): value is null | undefined {
  return value === null || value === undefined;
}

// null과 undefined는 같은 부재로 본다(V1/V2 기록에 없는 블록 대응).
// 나머지는 문자열 그대로 대조한다.
function sameText(a: unknown, b: unknown): boolean {
  if (isAbsent(a) || isAbsent(b)) return isAbsent(a) && isAbsent(b);
  return typeof a === "string" && typeof b === "string" && a === b;
}

// Core가 datetime으로 보관했다가 ISO로 돌려주므로 Z/+00:00 표기 차이를
// 순간 비교로 흡수한다. 둘 다 nullish면 같고, 한쪽만이면 다르다. 파싱
// 불가도 불일치로 둔다.
function sameInstant(a: unknown, b: unknown): boolean {
  if (isAbsent(a) || isAbsent(b)) return isAbsent(a) && isAbsent(b);
  if (typeof a !== "string" || typeof b !== "string") return false;
  const ta = Date.parse(a);
  const tb = Date.parse(b);
  return Number.isFinite(ta) && Number.isFinite(tb) && ta === tb;
}

function sameUpstream(a: unknown, b: unknown): boolean {
  if (isAbsent(a) || isAbsent(b)) return isAbsent(a) && isAbsent(b);
  if (typeof a !== "object" || typeof b !== "object") return false;
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  return sameText(left.sourceUri, right.sourceUri)
    && sameText(left.sourceSha256, right.sourceSha256)
    && sameText(left.licenceDeclaration, right.licenceDeclaration)
    && sameText(left.retrievalNote, right.retrievalNote);
}

function sameDerivative(a: unknown, b: unknown): boolean {
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

function echoArtifactsMatch(echoArtifacts: unknown, expected: DeclarationEcho["artifacts"]): boolean {
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

function echoDeclarationBlocksMatch(submission: unknown, expected: DeclarationEcho): boolean {
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

function echoSubmissionMatches(submission: unknown, expected: DeclarationEcho): boolean {
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
function declarationEchoOfRequest(body: V3DeclarationBody): DeclarationEcho {
  // 신규 V3 동결 요청서에서 대조용 신원을 뽑는다. BFF wire 본문 키 그대로를
  // 쓴다 — Core는 값을 보관했다가 같은 키로 돌려준다. V3 고정 필드는 그대로
  // 두고, 시간은 순간 대조로 표기 차이를 흡수한다.
  return {
    submissionId: body.submissionId,
    revision: 1,
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
function retainedEchoOf(submission: unknown): DeclarationEcho | null {
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
// 계약 버전·필드 모양을 새로 지어내지 않고, 화면 진입이 이미 쓰는
// submissionRef 패턴과 BFF가 고정하는 revision 1만 함께 확인한다.
function isRevisionViewForAttempt(
  value: unknown,
  expected: AttemptEcho,
  state: "REGISTERED" | "SEALED",
): value is Revision {
  if (!value || typeof value !== "object") return false;
  const view = value as Record<string, unknown>;
  if (typeof view.submissionRef !== "string" || !SUBMISSION_REF_PATTERN.test(view.submissionRef)) return false;
  if (expected.submissionRef !== null && view.submissionRef !== expected.submissionRef) return false;
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
function sealedManifestMatches(manifest: unknown, expected: DeclarationEcho, submissionDigest: string): boolean {
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

type UploadGrantView = { artifactId: string; uploadUrl: string; requiredHeaders: Record<string, string> };

// grant 응답의 화면 측 모양 — Core grant 화면의 실제 모양만 본다(대상·주소·
// 요청 헤더). 직접 PUT은 검증된 이 capability로만 내보낸다.
function isUploadGrantView(value: unknown): value is UploadGrantView {
  if (!value || typeof value !== "object") return false;
  const grant = value as Record<string, unknown>;
  return typeof grant.artifactId === "string" &&
    typeof grant.uploadUrl === "string" && grant.uploadUrl.length > 0 &&
    !!grant.requiredHeaders && typeof grant.requiredHeaders === "object" &&
    Object.values(grant.requiredHeaders as Record<string, unknown>).every((header) => typeof header === "string");
}

function isExternalArtifactInspectionView(value: unknown): value is ExternalArtifactInspectionView {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  const inspection = candidate.inspection;
  const display = candidate.display;
  return (candidate.registrationState === "REGISTERED" || candidate.registrationState === "SEALED") &&
    (candidate.sealState === "UNSEALED" || candidate.sealState === "SEALED") &&
    !!inspection && typeof inspection === "object" && typeof (inspection as Record<string, unknown>).state === "string" &&
    !!display && typeof display === "object" && typeof (display as Record<string, unknown>).state === "string";
}

async function hashFile(file: File, workers: Set<Worker>, onProgress: (bytes: number) => void, signal: AbortSignal): Promise<HashResult> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("../../lib/workers/file-sha256.worker.ts", import.meta.url));
    let settled = false;
    let onAbort: () => void = () => undefined;
    const finish = () => {
      workers.delete(worker);
      worker.terminate();
      signal.removeEventListener("abort", onAbort);
    };
    const settle = (result: { value: HashResult } | { error: Error }) => {
      if (settled) return;
      settled = true;
      finish();
      if ("error" in result) reject(result.error);
      else resolve(result.value);
    };
    onAbort = () => settle({ error: abortError() });
    workers.add(worker);
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) {
      onAbort();
      return;
    }
    const id = crypto.randomUUID();
    worker.onmessage = ({ data }) => {
      if (data.id !== id) return;
      if (typeof data.progress === "number") onProgress(data.progress);
      if (data.error) settle({ error: new Error(data.error) });
      if (data.sha256) settle({ value: { file, sha256: data.sha256, size: data.size } });
    };
    worker.onerror = () => settle({ error: new Error("file hashing failed") });
    worker.postMessage({ id, file, chunkBytes: 1024 * 1024 });
  });
}

function artifact(kind: ExternalArtifactKind, value: HashResult, crs: string): ArtifactDeclaration {
  // AX-3: 헤더에서 읽었거나 운영자가 고친 좌표계는 고객 신고일 뿐이다. 빈 칸은 신고하지 않는다.
  const declaredCrs = crs.trim() === "" ? null : crs.trim();
  return { artifactId: kind, kind, fileName: value.file.name, format: "GeoTIFF", contentType: "application/octet-stream", declaredSha256: value.sha256, declaredSizeBytes: value.size, declaredCrs, declaredVerticalReference: null, declaredGsdM: null };
}

async function recognizeHeader(file: File, signal: AbortSignal): Promise<HeaderRecognitionState> {
  try {
    return { status: "recognized", value: recognizeGeoTiffHeader(await readGeoTiffHeader(file, signal)) };
  } catch (error) {
    if (isAbortError(error)) throw error;
    return { status: "not-geotiff" };
  }
}

function exactBindingsMatch(expected: NonNullable<Revision["submission"]["artifacts"]>, actual: readonly ArtifactDeclaration[]): boolean {
  return expected.length === actual.length && expected.every((item) => {
    const selected = actual.find((candidate) => candidate.kind === item.kind);
    return selected !== undefined && selected.declaredSha256 === item.declaredSha256 && selected.declaredSizeBytes === item.declaredSizeBytes;
  });
}

/**
 * 자식(증거 패널)이 부모(결과 워크플로)로 전달하는 사용 결정의 형태 검사.
 * ELIGIBLE/RESTRICTED/BLOCKED 만 살리고, 결측·오염 값은 null으로 버린다.
 * 순수 함수이므로 모듈에 둔다 — 컴포넌트 안에서 만들면 매 렌더 새 참조가
 * 되어 자식 알림 effect가 불필요하게 다시 돈다.
 */
function volumeDecisionReceiver(store: (decision: ExternalRelativeVolumeDecision | null) => void) {
  return (value: {
    decisionId: string;
    decisionDigest?: string;
    verdict: string;
    reasons: string[];
    remediations: string[];
  } | null) => {
    if (!value || !value.decisionDigest || (value.verdict !== "ELIGIBLE" && value.verdict !== "RESTRICTED" && value.verdict !== "BLOCKED")) {
      store(null);
      return;
    }
    store({
      decisionId: value.decisionId,
      decisionDigest: value.decisionDigest,
      verdict: value.verdict,
      reasons: value.reasons,
      remediations: value.remediations,
    });
  };
}

function ExternalReconstructionPanelState({ workOrderId, siteId = "", expectedEpochId, canWrite, permissions, initialReport, requiresCaptureInterval = false, newIntentAllowed = true, workAreaNames, accountIdentity, legacyDecisionClosed = false }: { workOrderId: string; siteId?: string; expectedEpochId: string | null; canWrite: boolean; permissions?: readonly string[]; initialReport?: TrustedExternalResultLink; requiresCaptureInterval?: boolean; newIntentAllowed?: boolean; workAreaNames?: Readonly<Record<string, string>>; accountIdentity?: { fingerprint: string } | null; legacyDecisionClosed?: boolean }) {
  const legacyDetails = useRef<HTMLDetailsElement>(null);
  // V1은 보존 기능이지 현재 분석 진입점이 아니다. 기본은 접되 기존 결과·제안
  // 딥링크는 초기 진입과 같은 페이지 이동 모두에서 내용을 드러내야 한다.
  useEffect(() => {
    const revealLegacyTarget = () => {
      const hash = window.location.hash;
      if ((hash === "#external-volume" || hash === "#external-result") && legacyDetails.current) {
        legacyDetails.current.open = true;
        document.getElementById(hash.slice(1))?.scrollIntoView?.({ block: "start" });
      }
    };
    revealLegacyTarget();
    window.addEventListener("hashchange", revealLegacyTarget);
    return () => window.removeEventListener("hashchange", revealLegacyTarget);
  }, []);
  const workers = useRef(new Set<Worker>());
  const scope = useRef(0);
  const listAbort = useRef<AbortController | null>(null);
  const inspectionAbort = useRef(new Map<string, AbortController>());
  const hashAbort = useRef<AbortController | null>(null);
  const submissionAbort = useRef<AbortController | null>(null);
  const inspectionAutoRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inspectionAutoRefreshBudget = useRef(0);
  const inspectionAutoRefreshInFlight = useRef(false);
  const [submissionId, setSubmissionId] = useState(attemptId);
  const [submittedAt, setSubmittedAt] = useState(utcSeconds);
  const [hashing, setHashing] = useState(false);
  const [hashProgress, setHashProgress] = useState<number | null>(null);
  const [softwareName, setSoftwareName] = useState("");
  const [softwareVersion, setSoftwareVersion] = useState("");
  const [producerKnowledge, setProducerKnowledge] = useState<ExternalV3ProducerKnowledge>("DECLARED");
  const [sourceNote, setSourceNote] = useState("");
  const [captureBasis, setCaptureBasis] = useState<ExternalV3CaptureBasis>(() => requiresCaptureInterval ? "EXACT_INTERVAL" : "UNKNOWN");
  const [captureStartedLocal, setCaptureStartedLocal] = useState("");
  const [captureEndedLocal, setCaptureEndedLocal] = useState("");
  const [captureDateLocal, setCaptureDateLocal] = useState("");
  const [captureIntervalTouched, setCaptureIntervalTouched] = useState(false);
  const [retentionLocus, setRetentionLocus] = useState<ExternalV3RetentionLocus>("unknown");
  const [retentionDetail, setRetentionDetail] = useState("");
  const [upstreamUri, setUpstreamUri] = useState("");
  const [upstreamSha, setUpstreamSha] = useState("");
  const [upstreamLicence, setUpstreamLicence] = useState("");
  const [upstreamNote, setUpstreamNote] = useState("");
  const [exportToolName, setExportToolName] = useState("");
  const [exportToolVersion, setExportToolVersion] = useState("");
  const [exportSettingsDigest, setExportSettingsDigest] = useState("");
  const [exportedAtLocal, setExportedAtLocal] = useState("");
  const [exportNote, setExportNote] = useState("");
  const [ortho, setOrtho] = useState<HashResult | null>(null);
  const [dsm, setDsm] = useState<HashResult | null>(null);
  const [headers, setHeaders] = useState<Partial<Record<ExternalArtifactKind, HeaderRecognitionState>>>({});
  const [declaredCrs, setDeclaredCrs] = useState<Record<ExternalArtifactKind, string>>({ ortho: "", dsm: "" });
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [inspectionByRevision, setInspectionByRevision] = useState<Map<string, InspectionLoad>>(new Map());
  const [inspectionAutoRefreshStopped, setInspectionAutoRefreshStopped] = useState(false);
  const [visibleDisplay, setVisibleDisplay] = useState<string | null>(null);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [resume, setResume] = useState<Revision | null>(null);
  const [frozenAttempt, setFrozenAttempt] = useState<FrozenAttempt | null>(null);
  // 명시적 재개에 고정한 서버 확인 계정 비교값 — 신규 동결의 continuity와
  // 같은 역할을 하며, 재개 grant·seal 호출에 같은 값을 싣는다.
  const [resumeContinuity, setResumeContinuity] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  // 오류는 alert로, 진행·완료 안내는 status로 읽힌다. 같은 문자열이라도
  // 화면읽기 맥락이 다르므로 톤을 함께 둔다.
  const [messageAlert, setMessageAlert] = useState(false);
  const say = (text: string | null, alert = false) => {
    setMessage(text);
    setMessageAlert(alert);
  };
  // 같은 제출의 연속 클릭·이중 전송을 막는다. 응답 미확인 뒤의 명시적 재시도는
  // 같은 식별자로 보내므로 잠금과 충돌하지 않는다.
  const submitLock = useRef(false);
  // 등록 기준에 맞지 않는 파일 이름 — 슬롯별로 둔다. 같은 내용의 POST·동결을
  // 막고, 이전에 확인한 선택을 조용히 내보내지 않는다. 유효한 다시 선택·
  // 지우기로만 슬롯마다 푼다.
  const [nameIssues, setNameIssues] = useState<Record<ExternalArtifactKind, { fileName: string; reason: string } | null>>({ ortho: null, dsm: null });
  // 422로 분류된 선언 — 같은 식별자로는 다시 시도해도 접수되지 않는다. 조용히
  // 버리지 않고, 명시적인 새 등록으로만 새 식별자를 만든다.
  const [payloadRejected, setPayloadRejected] = useState(false);
  // 확인된 봉인(SEALED echo + 현 범위) — 같은 파일의 반복 업로드·승인을 막는다.
  // 응답 미확인(uncertain)에는 세우지 않고, 명시적인 새 등록·이어하기로만 푼다.
  // 응답 미확인(uncertain)에는 세우지 않고, 명시적인 새 등록·이어하기로만 푼다.
  const [sealedComplete, setSealedComplete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [relativeVolumeDecision, setRelativeVolumeDecision] = useState<ExternalRelativeVolumeDecision | null>(null);
  const [singleVolumeDecision, setSingleVolumeDecision] = useState<ExternalRelativeVolumeDecision | null>(null);
  const [documentVisible, setDocumentVisible] = useState(true);

  const captureStartedAt = captureBasis === "EXACT_INTERVAL" && captureStartedLocal ? seoulDateTimeLocalToUtc(captureStartedLocal) : null;
  const captureEndedAt = captureBasis === "EXACT_INTERVAL" && captureEndedLocal ? seoulDateTimeLocalToUtc(captureEndedLocal) : null;
  // 서버 확인 계정 비교값 — page가 서버에서 읽어 내려준 값의 모양만 본다.
  // 미확인이면 새 쓰기를 보내지 않고 설명하되 읽기는 유지한다. BFF 비교
  // 보조일 뿐 권한이 아니다.
  const continuity = typeof accountIdentity?.fingerprint === "string" && CONTINUITY_FINGERPRINT_PATTERN.test(accountIdentity.fingerprint)
    ? accountIdentity.fingerprint
    : null;
  // EXACT를 고르면 순서가 맞는 구간이 있어야 한다. 비어 있으면 UNKNOWN을 고른다.
  // DATE_ONLY는 달력 날짜 하나, UNKNOWN은 항상 유효하다.
  const captureValid = captureBasis === "EXACT_INTERVAL"
    ? captureStartedAt !== null && captureEndedAt !== null && captureStartedAt < captureEndedAt
    : captureBasis === "DATE_ONLY"
      ? isPublisherCalendarDate(captureDateLocal)
      : true;

  const currentScope = useCallback((value: number) => scope.current === value, []);
  const loadInspection = useCallback(async (
    revision: Revision,
    requestScope = scope.current,
    { automatic = false }: { automatic?: boolean } = {},
  ) => {
    const key = inspectionKey(revision);
    inspectionAbort.current.get(key)?.abort();
    const controller = new AbortController();
    inspectionAbort.current.set(key, controller);
    if (currentScope(requestScope)) setInspectionByRevision((current) => {
      const next = new Map(current);
      next.set(key, { phase: "loading", previous: retainedInspectionView(current.get(key)) });
      return next;
    });
    try {
      const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/inspection`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("inspection could not be loaded");
      const view: unknown = await response.json();
      if (!isExternalArtifactInspectionView(view)) throw new Error("inspection payload is malformed");
      if (!currentScope(requestScope) || inspectionAbort.current.get(key) !== controller) return;
      setInspectionByRevision((current) => new Map(current).set(key, { phase: "ready", view }));
    } catch (error) {
      if (isAbortError(error) || !currentScope(requestScope) || inspectionAbort.current.get(key) !== controller) return;
      setInspectionByRevision((current) => {
        const next = new Map(current);
        next.set(key, { phase: "error", previous: retainedInspectionView(current.get(key)) });
        return next;
      });
      if (automatic) setInspectionAutoRefreshStopped(true);
    } finally {
      if (inspectionAbort.current.get(key) === controller) inspectionAbort.current.delete(key);
    }
  }, [currentScope, workOrderId]);
  const load = useCallback(async (requestScope = scope.current) => {
    listAbort.current?.abort();
    const controller = new AbortController();
    listAbort.current = controller;
    if (currentScope(requestScope)) setListState("loading");
    try {
      const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions`, { signal: controller.signal });
      if (!response.ok) throw new Error("declarations could not be listed");
      const result = await response.json() as { submissions: Revision[] };
      if (!currentScope(requestScope) || listAbort.current !== controller) return;
      setRevisions(result.submissions);
      setInspectionByRevision(new Map());
      setInspectionAutoRefreshStopped(false);
      setVisibleDisplay(null);
      void Promise.all(result.submissions.map((revision) => loadInspection(revision, requestScope)));
      setListState("ready");
    } catch (error) {
      if (isAbortError(error) || !currentScope(requestScope) || listAbort.current !== controller) return;
      setListState("error");
    } finally {
      if (listAbort.current === controller) listAbort.current = null;
    }
  }, [currentScope, loadInspection, workOrderId]);

  // The keyed parent below remounts for a new work order, so this effect owns one scope only.
  useEffect(() => {
    const requestScope = scope.current + 1;
    scope.current = requestScope;
    const workerSet = workers.current;
    const inspectionControllers = inspectionAbort.current;
    void load(requestScope);
    return () => {
      if (!currentScope(requestScope)) return;
      scope.current += 1;
      listAbort.current?.abort();
      inspectionControllers.forEach((controller) => controller.abort());
      inspectionControllers.clear();
      hashAbort.current?.abort();
      submissionAbort.current?.abort();
      if (inspectionAutoRefreshTimer.current !== null) clearTimeout(inspectionAutoRefreshTimer.current);
      inspectionAutoRefreshTimer.current = null;
      listAbort.current = null;
      hashAbort.current = null;
      submissionAbort.current = null;
      workerSet.forEach((worker) => worker.terminate());
      workerSet.clear();
    };
  }, [currentScope, load]);

  useEffect(() => {
    const updateVisibility = () => setDocumentVisible(document.visibilityState !== "hidden");
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    if (inspectionAutoRefreshTimer.current !== null) {
      clearTimeout(inspectionAutoRefreshTimer.current);
      inspectionAutoRefreshTimer.current = null;
    }
    const active = revisions.filter((revision) => {
      const load = inspectionByRevision.get(inspectionKey(revision));
      const view = retainedInspectionView(load);
      return view !== null && presentExternalInspectionStatus(view).autoRefresh;
    });
    if (!documentVisible || inspectionAutoRefreshStopped || active.length === 0 || inspectionAutoRefreshBudget.current >= AUTO_INSPECTION_REFRESH_BUDGET) return;
    inspectionAutoRefreshTimer.current = setTimeout(() => {
      inspectionAutoRefreshTimer.current = null;
      if (document.visibilityState === "hidden" || inspectionAutoRefreshInFlight.current) return;
      inspectionAutoRefreshInFlight.current = true;
      inspectionAutoRefreshBudget.current += 1;
      void Promise.all(active.map((revision) => loadInspection(revision, scope.current, { automatic: true }))).finally(() => {
        inspectionAutoRefreshInFlight.current = false;
      });
    }, AUTO_INSPECTION_REFRESH_DELAY_MS);
    return () => {
      if (inspectionAutoRefreshTimer.current !== null) {
        clearTimeout(inspectionAutoRefreshTimer.current);
        inspectionAutoRefreshTimer.current = null;
      }
    };
  }, [documentVisible, inspectionAutoRefreshStopped, inspectionByRevision, loadInspection, revisions]);

  // 목록 다시 시도는 목록만 다시 읽는다. 상단 배너의 서버 상태 갱신에
  // router.refresh를 쓰지 않는다 — refresh는 영향받지 않은 클라이언트 상태만
  // 유지하므로, 서버 조회가 실패하거나 context가 unverified면 새 RSC가 이
  // 패널을 통째로 없애 입력·파일·동결 시도를 잃는다. 배너는 복구 뒤에도 이전
  // 정보일 수 있음을 스스로 밝힌다.

  const cancelHash = () => {
    const controller = hashAbort.current;
    if (!controller) return;
    hashAbort.current = null;
    controller.abort();
    setHashing(false);
    setHashProgress(null);
  };

  const select = async (kind: ExternalArtifactKind, file?: File) => {
    if (!file || hashing || frozenAttempt || (!newIntentAllowed && !resume)) return;
    // 이어하기(등록된 참조의 바이트 대조)는 새 신고가 아니라 파일 이름 문법을
    // 적용하지 않는다. 새 등록만 해시 같은 비싼 확인 전에 파일 이름을 검사한다.
    if (!resume) {
      const issue = describeExternalBasenameIssue(file.name);
      if (issue !== null) {
        setNameIssues((current) => ({ ...current, [kind]: { fileName: file.name, reason: issue } }));
        return;
      }
    }
    const requestScope = scope.current;
    const controller = new AbortController();
    hashAbort.current?.abort();
    hashAbort.current = controller;
    setHashing(true);
    setHashProgress(0);
    try {
      const [result, header] = await Promise.all([
        hashFile(file, workers.current, setHashProgress, controller.signal),
        recognizeHeader(file, controller.signal),
      ]);
      if (!currentScope(requestScope) || hashAbort.current !== controller) return;
      if (kind === "ortho") {
        if (ortho && (ortho.sha256 !== result.sha256 || ortho.size !== result.size)) {
          setSubmissionId(attemptId());
          setSubmittedAt(utcSeconds());
        }
        setOrtho(result);
      } else {
        if (dsm && (dsm.sha256 !== result.sha256 || dsm.size !== result.size)) {
          setSubmissionId(attemptId());
          setSubmittedAt(utcSeconds());
        }
        setDsm(result);
      }
      setHeaders((current) => ({ ...current, [kind]: header }));
      setNameIssues((current) => ({ ...current, [kind]: null }));
      if (!resume) {
        const recognized = header.status === "recognized" ? header.value : null;
        setDeclaredCrs((current) => ({ ...current, [kind]: recognized?.declaredCrs ?? "" }));
        const producer = recognized?.producer;
        if (producer) {
          // 운영자가 이미 적은 값은 덮지 않는다. 빈 칸만 헤더 값으로 채운다.
          setSoftwareName((current) => (current.trim() ? current : producer.name));
          if (producer.version) setSoftwareVersion((current) => (current.trim() ? current : producer.version ?? ""));
        }
      }
      say(null);
    } catch (error) {
      if (!isAbortError(error) && currentScope(requestScope) && hashAbort.current === controller) say("파일 정보를 확인하지 못했습니다.", true);
    } finally {      if (hashAbort.current === controller) {
        hashAbort.current = null;
        if (currentScope(requestScope)) {
          setHashing(false);
          setHashProgress(null);
        }
      }
    }
  };

  const selectResume = (revision: Revision) => {
    if (busy || hashing) return;
    // 명시적 재개에 현재 확인된 계정 비교값을 고정한다. 미확인이면 grant·
    // seal 쓰기를 보내지 않고 설명하되 목록·검사 읽기는 그대로 둔다.
    if (!continuity) {
      say("계정을 확인하지 못해 등록 이어하기를 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 등록 자료와 검사 상태 확인은 계속할 수 있습니다.", true);
      return;
    }
    setFrozenAttempt(null);
    setResume(revision);
    setResumeContinuity(continuity);
    setOrtho(null);
    setDsm(null);
    setNameIssues({ ortho: null, dsm: null });
    setSealedComplete(false);
    // 재개는 등록된 신고를 다시 보내지 않으므로 폼 값은 참고용으로만 둔다.
    const knowledge = revision.submission.producerDeclaration?.producerKnowledge;
    setProducerKnowledge(knowledge === "PARTIAL" || knowledge === "UNKNOWN" ? knowledge : "DECLARED");
    setSoftwareName(revision.submission.producerDeclaration?.softwareName ?? "");
    setSoftwareVersion(revision.submission.producerDeclaration?.softwareVersion ?? "");
    say("등록된 파일과 같은 파일을 다시 선택하세요.");
  };

  const startNewAttempt = () => {
    if (busy || hashing) return;
    if (!newIntentAllowed) {
      say("업무 종료 상태에서는 새 산출물 등록을 시작할 수 없습니다.", true);
      return;
    }
    setResume(null);
    setResumeContinuity(null);
    setFrozenAttempt(null);
    setPayloadRejected(false);
    setNameIssues({ ortho: null, dsm: null });
    setSealedComplete(false);
    setSubmissionId(attemptId());
    setSubmittedAt(utcSeconds());
    say(null);
  };

  // 슬롯은 서로 독립이다. 한 칸을 지워도 다른 칸의 확인된 선택을 버리지
  // 않는다. 이름 문제도 고친 칸만 푼다.
  const clearSlot = (kind: ExternalArtifactKind) => {
    if (busy || hashing || frozenAttempt) return;
    setNameIssues((current) => ({ ...current, [kind]: null }));
    if (kind === "ortho") {
      setOrtho(null);
      setHeaders((current) => {
        const next = { ...current };
        delete next.ortho;
        return next;
      });
      setDeclaredCrs((current) => ({ ...current, ortho: "" }));
    } else {
      setDsm(null);
      setHeaders((current) => {
        const next = { ...current };
        delete next.dsm;
        return next;
      });
      setDeclaredCrs((current) => ({ ...current, dsm: "" }));
    }
  };

  const metadataIssue = describeV3MetadataIssue({
    producerKnowledge, softwareName, softwareVersion, sourceNote,
    captureBasis, captureDateLocal,
    upstreamUri, upstreamSha,
    exportToolName, exportToolVersion, exportSettingsDigest, exportedAtLocal, exportNote,
  });
  const hasFile = Boolean(ortho || dsm);

  const freezeCurrentAttempt = (): FrozenAttempt | null => {
    if (!hasFile || !expectedEpochId || metadataIssue !== null || !captureValid || !continuity) return null;
    const name = softwareName.trim();
    const version = softwareVersion.trim();
    const uri = upstreamUri.trim();
    const toolName = exportToolName.trim();
    const toolVersion = exportToolVersion.trim();
    const exportedAt = exportedAtLocal ? seoulDateTimeLocalToUtc(exportedAtLocal) : null;
    const artifacts = Object.freeze([...(ortho ? [artifact("ortho", ortho, declaredCrs.ortho)] : []), ...(dsm ? [artifact("dsm", dsm, declaredCrs.dsm)] : [])]);
    const requestBody = Object.freeze({
      submissionId, expectedEpochId, submittedAt,
      producerKnowledge,
      softwareName: producerKnowledge === "UNKNOWN" ? null : name,
      softwareVersion: producerKnowledge === "DECLARED" ? version : null,
      sourceNote: sourceNote.trim() === "" ? null : sourceNote.trim(),
      captureBasis,
      captureStartedAt, captureEndedAt,
      captureDate: captureBasis === "DATE_ONLY" ? captureDateLocal : null,
      originalRetentionLocus: retentionLocus,
      originalRetentionDetail: retentionDetail.trim() === "" ? null : retentionDetail.trim(),
      upstreamSource: uri === "" ? null : {
        sourceUri: uri,
        sourceSha256: upstreamSha.trim() === "" ? null : upstreamSha.trim(),
        licenceDeclaration: upstreamLicence.trim() === "" ? null : upstreamLicence.trim(),
        retrievalNote: upstreamNote.trim() === "" ? null : upstreamNote.trim(),
      },
      derivativeExport: toolName === "" ? null : {
        toolName, toolVersion,
        settingsDigest: exportSettingsDigest.trim() === "" ? null : exportSettingsDigest.trim(),
        exportedAt,
        exportNote: exportNote.trim() === "" ? null : exportNote.trim(),
      },
      artifacts,
    });
    const bindings = Object.freeze([...(ortho ? [{ slot: "ortho" as const, artifactId: "ortho", value: ortho }] : []), ...(dsm ? [{ slot: "dsm" as const, artifactId: "dsm", value: dsm }] : [])]);
    return Object.freeze({ requestBody, bindings, continuity });
  };

  const submit = async () => {
    if (!hasFile || hashing || busy || sealedComplete || submitLock.current) return;
    let revision = resume;
    let bindings: FrozenAttempt["bindings"];
    let attempt = frozenAttempt;
    // 동결 전 첫 신고인지 — 확정 거부(401/403/404)면 동결을 풀고 입력·파일
    // 선택은 둔다. 동결 후 재시도의 같은 코드는 이번 재시도만 확정할 뿐이므로
    // 원래 동결을 유지하고 모름으로 둔다(목록 확인 경로와 함께).
    const firstDeclaration = !revision && attempt === null;
    if (revision) {
      // 재개는 종류·해시·크기만 대조한다(이미 등록된 신고를 다시 보내지 않는다).
      // 계약상 종류는 제출 내 유일하므로(V1/V2/V3 모두 kind 중복 금지) 종류로
      // 저장된 artifact_id를 찾고, grant·PUT 결속은 그 저장 식별자로 한다.
      // 슬롯 키(kind)를 grant artifactId에 그대로 쓰지 않는다 — V1/V2의
      // 사용자 정의 ID 기록은 읽어서 대조할 수 있어도 슬롯 키로는 결속할 수
      // 없기 때문이다. 저장 식별자를 찾지 못하면 모름으로 둔다.
      const selectedArtifacts = [...(ortho ? [artifact("ortho", ortho, "")] : []), ...(dsm ? [artifact("dsm", dsm, "")] : [])];
      const expectedArtifacts = revision.submission.artifacts ?? [];
      if (!exactBindingsMatch(expectedArtifacts, selectedArtifacts)) {
        say("선택한 파일이 등록된 자료의 종류, 해시 또는 크기와 일치하지 않습니다.", true);
        return;
      }
      const storedIdByKind = new Map(expectedArtifacts.map((item) => [item.kind, item.artifactId]));
      const orthoArtifactId = ortho ? storedIdByKind.get("ortho") : undefined;
      const dsmArtifactId = dsm ? storedIdByKind.get("dsm") : undefined;
      if ((ortho && typeof orthoArtifactId !== "string") || (dsm && typeof dsmArtifactId !== "string")) {
        say(unknownResponseMessage(), true);
        return;
      }
      bindings = [...(ortho && orthoArtifactId ? [{ slot: "ortho" as const, artifactId: orthoArtifactId, value: ortho }] : []), ...(dsm && dsmArtifactId ? [{ slot: "dsm" as const, artifactId: dsmArtifactId, value: dsm }] : [])];
    } else {
      // 기준에 맞지 않는 이름·422 분류 선언은 같은 내용으로 보내지 않는다.
      // 슬롯마다 남은 문제가 하나라도 있으면 동결·전송하지 않는다.
      if (nameIssues.ortho || nameIssues.dsm) {
        say("파일 이름이 등록 기준에 맞지 않아 보낼 수 없습니다. 조건에 맞는 복사본을 다시 선택하거나 이전 선택을 지우세요.", true);
        return;
      }
      if (payloadRejected) {
        say("제출 내용이 등록 기준에 맞지 않아 접수되지 않았습니다. 같은 내용으로는 다시 시도해도 접수되지 않습니다. 새로 등록하기로 새 식별자를 만들어 다시 시도하세요.", true);
        return;
      }
      if (!attempt) {
        if (!newIntentAllowed) {
          say("업무 종료 상태에서는 새 산출물 등록을 시작할 수 없습니다.", true);
          return;
        }
        // 서버 확인 계정이 없으면 새 쓰기를 보내지 않는다. 읽기는 유지된다.
        if (!continuity) {
          say("계정을 확인하지 못해 산출물 등록을 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 등록 자료와 검사 상태 확인은 계속할 수 있습니다.", true);
          return;
        }
        if (metadataIssue !== null) {
          say(metadataIssue, true);
          return;
        }
        if (!captureValid) {
          setMessage(captureBasis === "DATE_ONLY"
            ? "촬영 날짜만 아는 경우 YYYY-MM-DD 형식의 날짜를 입력하세요."
            : "촬영 시작과 종료 시각을 한국 표준시 기준으로 모두 입력하고 순서를 확인하세요.");
          return;
        }
        attempt = freezeCurrentAttempt();
        if (!attempt) return;
        setFrozenAttempt(attempt);
      }
      bindings = attempt.bindings;
    }

    // 이번 호출 묶음(등록·grant·seal)이 실어 보낼 계정 비교값 — 신규 동결 또는
    // 명시적 재개 시점에 고정한 값이며 호출 도중 바뀌지 않는다. BFF 비교
    // 보조일 뿐 권한이 아니다.
    const submitContinuity = attempt !== null ? attempt.continuity : resumeContinuity;
    if (!submitContinuity) {
      say("계정을 확인하지 못해 산출물 등록을 이어갈 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 등록 자료와 검사 상태 확인은 계속할 수 있습니다.", true);
      return;
    }

    if (submitLock.current) return;
    submitLock.current = true;
    const requestScope = scope.current;
    const controller = new AbortController();
    submissionAbort.current = controller;
    setBusy(true);
    setUploadProgress(null);
    say(null);
    try {
      if (!revision) {
        const declarationHeaders: Record<string, string> = { "content-type": "application/json" };
        declarationHeaders[CONTINUITY_FINGERPRINT_HEADER] = submitContinuity;
        const response = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions-v3`, { method: "POST", headers: declarationHeaders, body: JSON.stringify(attempt!.requestBody), signal: controller.signal });
        if (!response.ok) {
          const failureCode = responseCode(await response.json().catch(() => null));
          // 계정 연속성 거부 — 원래 시도를 버리지 않고 같은 화면의 같은
          // 시도로 돌아오게 둔다. 첫 시도·재시도를 가리지 않는다.
          if (response.status === 409 && failureCode === ACCOUNT_CONTINUITY_MISMATCH) {
            say(accountMismatchMessage(), true);
            return;
          }
          // 422는 내용 자체가 기준에 맞지 않는 분류 — 첫 신고에서만 확정한다.
          // 같은 식별자로는 다시 보내지 않는다. 동결된 시도는 버리지 않고
          // 명시적인 새 등록을 둔다.
          if (response.status === 422 && firstDeclaration) {
            setPayloadRejected(true);
            say("제출 내용이 등록 기준에 맞지 않아 접수되지 않았습니다. 같은 내용으로는 다시 시도해도 접수되지 않습니다. 새로 등록하기로 새 식별자를 만들어 파일과 입력값을 확인한 뒤 다시 시도하세요.", true);
            return;
          }
          // 재시도의 422는 이번 재시도만 확정할 뿐이다. 원래 모호한 요청이 이미
          // 접수됐을 수 있으므로 동결을 유지하고 모름으로 둔다. 되돌림이나
          // 부재를 단정하지 않는다.
          if (response.status === 422) {
            say("다시 보낸 요청이 등록 기준에 맞지 않아 접수되지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 파일 선택은 이 화면에 그대로 있습니다. 작업 목록에서 이미 제출됐는지 먼저 확인하세요. 내용이 잘못된 경우 새로 시작해 수정하세요.", true);
            return;
          }
          // 첫 신고의 401/403/404는 확정적이다 — BFF·Core가 저장 전에
          // 거부하므로 같은 식별자로 만든 제출이 없다. 동결을 풀고 입력·파일
          // 선택은 그대로 둔다. 동결 후 재시도의 같은 코드는 모름으로 둔다.
          if (firstDeclaration && (response.status === 401 || response.status === 403 || response.status === 404)) {
            setFrozenAttempt(null);
            say(response.status === 401
              ? "세션이 만료되어 산출물 등록을 시작하지 못했습니다. 입력과 파일 선택은 그대로 있습니다. 다른 탭에서 같은 계정으로 다시 로그인한 뒤 새로 등록하세요."
              : response.status === 403
                ? "산출물 등록 권한이 없어 시작하지 못했습니다. 입력과 파일 선택은 그대로 있습니다. 현장 담당자에게 산출물 등록 권한을 요청한 뒤 새로 등록하세요."
                : "작업 범위를 확인하지 못해 산출물 등록을 시작하지 못했습니다. 입력과 파일 선택은 그대로 있습니다. 작업 상태를 확인한 뒤 화면을 새로고침해 새로 등록하세요.", true);
            return;
          }
          throw new Error("registration failed");
        }
        // 2xx라도 이번 시도의 응답인지 확인한다 — 비어 있거나 다른 대상이면
        // 성공으로 표시하지 않고 동결을 유지한다. BFF는 신규 등록을 revision 1로
        // 고정하므로 echo의 revision도 함께 대조한다.
        const declared: unknown = await response.json().catch(() => null);
        const declarationEcho: AttemptEcho = {
          submissionRef: null,
          ...declarationEchoOfRequest(attempt!.requestBody),
        };
        if (!isRevisionViewForAttempt(declared, declarationEcho, "REGISTERED")) {
          // 같은 원본·같은 식별로 이미 봉인된 기록이 돌아왔다 — Core에서
          // 봉인했으나 응답을 잃은 뒤 같은 frozen 선언을 재전송하면 BFF는
          // 동일 digest의 실제 과거 record를 그대로 반환한다. echo 대조를
          // 통과한 SEALED만 실제 확인된 봉인으로 복구하고, PUT/grant/seal을
          // 다시 내지 않고 목록을 확인한다. 다르거나 불완전하면 모름으로
          // 둔다. 계정·원본 불일치 409는 위에서 이미 막혔고 여기서 성공으로
          // 바뀌지 않는다.
          if (isRevisionViewForAttempt(declared, declarationEcho, "SEALED")) {
            revision = declared;
            setSealedComplete(true);
            say("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
            // 목록만 다시 읽는다. 상단 배너의 서버 상태는 별도 화면 이동·
            // 새로고침 때 갱신되며, 그때 미제출 입력·동결 시도는 사라질 수
            // 있다. 자동 route refresh로 형제 초안을 잃게 하지 않는다.
            await load(requestScope);
            return;
          }
          say(unknownResponseMessage(), true);
          return;
        }
        revision = declared;
      }
      if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      const grantHeaders: Record<string, string> = {};
      grantHeaders[CONTINUITY_FINGERPRINT_HEADER] = submitContinuity;
      const grantsResponse = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/upload-grants`, { method: "POST", headers: grantHeaders, signal: controller.signal });
      if (!grantsResponse.ok) {
        if (grantsResponse.status === 409 && responseCode(await grantsResponse.json().catch(() => null)) === ACCOUNT_CONTINUITY_MISMATCH) {
          say(accountMismatchMessage(), true);
          return;
        }
        throw new Error("grant failed");
      }
      // grant 응답은 이번 시도가 결속한 저장 산출물 집합과 정확히 같아야 한다.
      // Core upload_grants는 저장 bindings를 1:1로 돌며 grant를 만들기 때문에
      // 정상 응답에 중복·여분·누락이 있을 수 없다. 어긋나면 전송을 시작하지
      // 않고 동결을 유지한다. 직접 PUT은 아래에서 이 grant capability로만
      // 나가며, 조회는 슬롯 키가 아니라 결속된 저장 artifact_id로 한다.
      const grantsPayload: unknown = await grantsResponse.json().catch(() => null);
      const grantList = grantsPayload && typeof grantsPayload === "object" && Array.isArray((grantsPayload as { grants?: unknown }).grants)
        ? (grantsPayload as { grants: unknown[] }).grants
        : null;
      const grants = grantList !== null && grantList.every(isUploadGrantView) ? grantList : null;
      const grantIds = grants !== null ? grants.map((grant) => grant.artifactId) : null;
      const expectedGrantIds = bindings.map(({ artifactId }) => artifactId);
      if (!grants || grantIds === null || new Set(grantIds).size !== grantIds.length || grantIds.length !== expectedGrantIds.length || !expectedGrantIds.every((artifactId) => grantIds.includes(artifactId))) {
        say(unknownResponseMessage(), true);
        return;
      }
      for (const { slot, artifactId, value } of bindings) {
        const grant = grants.find((item) => item.artifactId === artifactId);
        if (!grant) throw new Error("missing upload grant");
        setUploadProgress({ artifactId: slot, transferredBytes: 0, totalBytes: value.size, phase: "uploading" });
        await putExternalReconstructionFile(grant, value.file, controller.signal, (transferredBytes) => {
          if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
          setUploadProgress({ artifactId: slot, transferredBytes, totalBytes: value.size, phase: transferredBytes === value.size ? "uploaded" : "uploading" });
        });
        if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      }
      const sealHeaders: Record<string, string> = {};
      sealHeaders[CONTINUITY_FINGERPRINT_HEADER] = submitContinuity;
      const seal = await fetch(`/api/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions/${encodeURIComponent(revision.submissionRef)}/revisions/${revision.submission.revision}/seal`, { method: "POST", headers: sealHeaders, signal: controller.signal });
      const sealPayload: unknown = await seal.json().catch(() => null);
      if (!seal.ok) {
        if (seal.status === 409 && responseCode(sealPayload) === ACCOUNT_CONTINUITY_MISMATCH) {
          say(accountMismatchMessage(), true);
          return;
        }
        throw new Error("seal failed");
      }
      if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      // 봉인 응답이 이번 시도의 것인지 확인한다 — 비어 있거나 SEALED가
      // 아니거나 다른 대상이면 성공으로 표시하지 않고 같은 시도 복구로 남긴다.
      // 신규면 동결 요청서, 재개면 유지된 제출 기록과 대조한다. ref는 요청
      // 경로에 쓴 것과 정확히 같아야 한다.
      const sealSource: DeclarationEcho | null = attempt !== null
        ? declarationEchoOfRequest(attempt.requestBody)
        : retainedEchoOf(revision.submission);
      const sealEcho: AttemptEcho | null = sealSource === null ? null : {
        submissionRef: revision.submissionRef,
        ...sealSource,
      };
      if (!sealEcho || !isRevisionViewForAttempt(sealPayload, sealEcho, "SEALED")) {
        say(unknownResponseMessage(), true);
        return;
      }
      revision = sealPayload;
      if (!currentScope(requestScope) || submissionAbort.current !== controller) return;
      // 확인된 봉인에서만 완료로 잠근다. 응답 미확인 경로(throw·중단)는 동결된
      // 시도를 그대로 두고 같은 식별자로 다시 확인할 수 있게 둔다.
      // 목록만 다시 읽는다 — 상단 배너의 서버 상태는 별도 화면 이동·새로고침
      // 때 갱신되며, 그때 미제출 입력·동결 시도는 사라질 수 있다. 자동 route
      // refresh로 형제 초안을 잃게 하지 않는다.
      setSealedComplete(true);
      say("파일 등록을 확인했습니다. 파일 형식과 측정 적합성 확인은 아직 진행되지 않았습니다.");
      await load(requestScope);
    } catch (error) {
      if (!isAbortError(error) && currentScope(requestScope) && submissionAbort.current === controller) say(unknownResponseMessage(), true);
    } finally {
      submitLock.current = false;
      if (submissionAbort.current === controller) {
        submissionAbort.current = null;
        if (currentScope(requestScope)) setBusy(false);
      }
    }
  };

  const cancelSubmission = () => {
    const controller = submissionAbort.current;
    if (!controller) return;
    submissionAbort.current = null;
    controller.abort();
    setBusy(false);
    setUploadProgress(null);
    say("등록 중단을 요청했습니다. 이미 접수되거나 전송된 내용이 있을 수 있습니다. 목록을 다시 읽어 실제 상태를 확인하세요.");
    // 중단은 전송 취소를 보장하지 않는다. 이미 접수된 내용이 있을 수 있으니
    // 목록을 다시 읽어 실제 상태를 보여준다.
    void load();
  };

  const metadataReady = Boolean(resume) || (metadataIssue === null && captureValid);
  const canSubmit = hasFile && !busy && !hashing && !sealedComplete && !nameIssues.ortho && !nameIssues.dsm && metadataReady
    && (Boolean(resume && resumeContinuity) || (!payloadRejected && (Boolean(frozenAttempt) || Boolean(newIntentAllowed && expectedEpochId && continuity))));
  const formIsFrozen = Boolean(frozenAttempt || resume);

  // 자식의 알림 effect 의존성이므로 매 렌더 새 함수가 되지 않게 고정한다.
  // volumeDecisionReceiver는 모듈 수준 순수 함수이고 store는 안정적이므로
  // 렌더 루프가 생기지 않는다.
  const receiveRelativeVolumeDecision = useMemo(() => volumeDecisionReceiver(setRelativeVolumeDecision), []);
  const receiveSingleVolumeDecision = useMemo(() => volumeDecisionReceiver(setSingleVolumeDecision), []);

  // 유지된 revision이 있으면 새 등록 폼은 펼침 뒤에 둔다. 단, 진행 중·동결된
  // 시도(파일 선택·응답 미확인 재시도·재개·전송 중·안내 문구)는 절대 숨기지
  // 않는다 — compactness보다 시도 보존이 우선이다.
  const hasRetainedRevisions = listState === "ready" && revisions.length > 0;
  const newFormPristine = !formIsFrozen && !busy && !hashing && !uploadProgress && !ortho && !dsm && message === null;
  const collapseNewForm = hasRetainedRevisions && newFormPristine;

  return <><section id="external-submissions" className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 text-[13px]">
    <div><h2 className="text-[16px] font-bold">관측 자료 등록</h2><p className="text-ink-2">외부에서 준비한 파일을 선택해 등록합니다. 파일 검사와 분석에 사용할 수 있는지 확인하는 절차는 별도입니다.</p>
    <ol aria-label="등록 순서" className="mt-2 grid grid-cols-3 gap-2 text-[12px]"><li className="border-b-2 border-line pb-2 text-ink-2">1. 신고 입력·파일 선택</li><li className="border-b-2 border-line pb-2 text-ink-2">2. 등록·전송·봉인</li><li className="border-b-2 border-line pb-2 text-ink-2">3. 검사 상태 확인</li></ol></div>
    {!newIntentAllowed && <p className="rounded-lg border border-line bg-sunk px-3 py-2 leading-5 text-ink-2">업무 종료 상태입니다. 새 산출물 등록은 시작할 수 없지만, 이미 등록한 파일의 업로드·봉인 상태와 결과는 계속 확인할 수 있습니다.</p>}
    {listState === "loading" && <p role="status" className="text-ink-2">등록 목록을 불러오는 중입니다.</p>}
    {listState === "error" && <div role="alert" className="flex flex-col items-start gap-2 text-ink-2"><p>등록 목록을 불러오지 못했습니다.</p><button className="btn w-fit" onClick={() => void load()}>목록 다시 시도</button></div>}
    {listState === "ready" && <ul className="flex flex-col gap-2 text-ink-2">{revisions.length === 0 ? <li><span>아직 등록된 관측 자료가 없습니다.</span>{" "}자료를 등록하면 파일 제출과 검사 상태를 이곳에서 확인할 수 있습니다.</li> : null}</ul>}
    {!canWrite && <p className="text-ink-2">조회 전용 계정입니다. 등록 자료와 검사 상태를 확인할 수 있습니다.</p>}
    {/* 1024px 미만 쓰기 경계는 폼 전체를 숨긴다. 펼침(summary)만 남기면 빈
        펼침이 되므로, 경계가 details 자체를 감싼다. 작은 화면 안내는 작업 상세
        상단의 노트북 계속 안내가 맡고, 여기에는 중복 안내를 두지 않는다. */}
    {canWrite && <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" inlineNotice={false} reason="노트북에서 같은 계정으로 이 작업 상세를 열어 정사영상·DSM 등록을 이어가세요.">
    <details open={collapseNewForm ? undefined : true}>
      <summary className="tap-target cursor-pointer font-semibold">새 산출물 등록</summary>
      <div className="mt-3 flex flex-col gap-3">
      <div className="flex flex-col gap-3">
        {resume ? <div className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2"><p>선택한 제출본의 등록 정보를 그대로 사용합니다. 여기서는 같은 파일의 전송만 재개하며, 제작·촬영 정보는 다시 신고하거나 변경하지 않습니다.</p>{describeProducerLine(resume.submission.producerDeclaration) && <p className="mt-1">저장된 신고 · {describeProducerLine(resume.submission.producerDeclaration)}</p>}</div> : <>
        <fieldset className="grid gap-2 rounded-lg border border-line bg-sunk p-3" disabled={busy || hashing || formIsFrozen || !newIntentAllowed}>
          <legend className="px-1 font-semibold">재구성 소프트웨어</legend>
          <p className="text-[12px] text-ink-2">실제 재구성한 소프트웨어를 아는 대로 선택하세요. ‘unknown’이라고 쓰지 않습니다.</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="재구성 소프트웨어 확인 방식">
            {(["DECLARED", "PARTIAL", "UNKNOWN"] as const).map((option) => (
              <label key={option} className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12px]">
                <input type="radio" name="producer-knowledge" value={option} checked={producerKnowledge === option} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={() => {
                  setProducerKnowledge(option);
                  if (option === "UNKNOWN") { setSoftwareName(""); setSoftwareVersion(""); }
                  if (option === "PARTIAL") { setSoftwareVersion(""); }
                }} />
                {option === "DECLARED" ? "이름과 버전 모두 알고 있음" : option === "PARTIAL" ? "이름만 알고 있음" : "미상"}
              </label>
            ))}
          </div>
          {producerKnowledge !== "UNKNOWN" && <label className="flex flex-col gap-1 font-semibold">재구성 소프트웨어 이름<input className="input" aria-label="재구성 소프트웨어 이름" value={softwareName} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setSoftwareName(event.target.value)} /></label>}
          {producerKnowledge === "DECLARED" && <label className="flex flex-col gap-1 font-semibold">재구성 소프트웨어 버전<input className="input" aria-label="재구성 소프트웨어 버전" value={softwareVersion} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setSoftwareVersion(event.target.value)} /></label>}
          <label className="flex flex-col gap-1 font-semibold">출처 기록 (선택)<input className="input" aria-label="재구성 소프트웨어 출처 기록" value={sourceNote} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setSourceNote(event.target.value)} /></label>
        </fieldset>
        <fieldset className="grid gap-2 rounded-lg border border-line bg-sunk p-3" disabled={busy || hashing || formIsFrozen || !newIntentAllowed}>
          <legend className="px-1 font-semibold">{captureBasis === "EXACT_INTERVAL" ? "촬영 시점 (한국 표준시)" : "촬영 시점"}</legend>
          <p className="text-[12px] text-ink-2">{requiresCaptureInterval ? "외부 관측 등록에는 촬영 구간 확인이 권장됩니다. 미상인 경우 그대로 등록되며, 이후 분석·비교 가능 여부는 별도로 확인합니다." : "촬영 방식을 선택하세요. 선택한 방식만 등록에 포함됩니다."}</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="촬영 시점 확인 방식">
            {(["EXACT_INTERVAL", "DATE_ONLY", "UNKNOWN"] as const).map((option) => (
              <label key={option} className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12px]">
                <input type="radio" name="capture-basis" value={option} checked={captureBasis === option} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={() => setCaptureBasis(option)} />
                {option === "EXACT_INTERVAL" ? "정확한 촬영 시각" : option === "DATE_ONLY" ? "촬영 날짜만 확인됨" : "촬영 시점 미상"}
              </label>
            ))}
          </div>
          {captureBasis === "EXACT_INTERVAL" && <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1">시작<input className="input" aria-label="촬영 시작 시각 (한국 표준시)" type="datetime-local" step="1" value={captureStartedLocal} onChange={(event) => { setCaptureIntervalTouched(true); setCaptureStartedLocal(event.target.value); }} />
              {captureStartedAt && <span className="text-[12px] text-ink-muted">선택: {formatKoreanDateTime(captureStartedAt, { dateStyle: "short", timeStyle: "short" })}</span>}
            </label>
            <label className="flex flex-col gap-1">종료<input className="input" aria-label="촬영 종료 시각 (한국 표준시)" type="datetime-local" step="1" value={captureEndedLocal} onChange={(event) => { setCaptureIntervalTouched(true); setCaptureEndedLocal(event.target.value); }} />
              {captureEndedAt && <span className="text-[12px] text-ink-muted">선택: {formatKoreanDateTime(captureEndedAt, { dateStyle: "short", timeStyle: "short" })}</span>}
            </label>
          </div>}
          {captureBasis === "DATE_ONLY" && <label className="flex flex-col gap-1">촬영 날짜 (날짜만 아는 경우)<input className="input" aria-label="촬영 날짜 (YYYY-MM-DD)" type="date" value={captureDateLocal} onChange={(event) => setCaptureDateLocal(event.target.value)} />
            {captureBasis === "DATE_ONLY" && formatPublisherCalendarDate(captureDateLocal) && <span className="text-[12px] text-ink-muted">선택: {formatPublisherCalendarDate(captureDateLocal)} · 시각 미상</span>}
          </label>}
          {captureBasis === "UNKNOWN" && <p className="text-[12px] text-ink-2">촬영 시점을 미상으로 등록합니다. 자정 시각 같은 추정값을 넣지 않습니다. 이후 분석·비교 가능 여부는 별도로 확인합니다.</p>}
          {captureBasis === "EXACT_INTERVAL" && captureIntervalTouched && !captureValid && <p role="alert" className="text-[12px] text-high-ink">시작과 종료를 모두 입력하고, 종료가 시작보다 늦은지 확인하세요.</p>}
        </fieldset>
        <fieldset className="grid gap-2 rounded-lg border border-line bg-sunk p-3" disabled={busy || hashing || formIsFrozen || !newIntentAllowed}>
          <legend className="px-1 font-semibold">촬영 원본 보관 위치</legend>
          <p className="text-[12px] text-ink-2">제출할 GeoTIFF가 아니라 재구성에 사용한 원본 사진·관측 자료의 보관 위치입니다. 원본 업로드는 요청하지 않습니다. 위치를 모르면 미상으로 두고, 공개 출처에 보관돼 있다고 추정하지 마세요.</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="원본 보관 위치">
            {(["customer_workstation", "upstream_source", "unknown"] as const).map((option) => (
              <label key={option} className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12px]">
                <input type="radio" name="original-retention" value={option} checked={retentionLocus === option} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={() => setRetentionLocus(option)} />
                {option === "customer_workstation" ? "고객 작업 장비에 있음" : option === "upstream_source" ? "공개 출처에 있음(확인된 경우만)" : "미상"}
              </label>
            ))}
          </div>
          <label className="flex flex-col gap-1 font-semibold">보관 위치 상세 (선택)<input className="input" aria-label="원본 보관 위치 상세" value={retentionDetail} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setRetentionDetail(event.target.value)} /></label>
        </fieldset>
        <details className="rounded-lg border border-line bg-sunk p-3 text-[12px]">
          <summary className="tap-target cursor-pointer font-semibold">원본 공개 출처 (선택)</summary>
          <p className="mt-1 leading-5 text-ink-2">공개 출처 기록이며, KSI가 해당 자료를 내려받거나 검증하지 않습니다. 권리 허락이 아닙니다.</p>
          <div className="mt-2 grid gap-2">
            <label className="flex flex-col gap-1 font-semibold">공개 출처 주소<input className="input" aria-label="원본 공개 출처 주소" value={upstreamUri} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} inputMode="url" placeholder="https://" onChange={(event) => setUpstreamUri(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">원본 확인값 (선택)<input className="input" aria-label="원본 확인값" value={upstreamSha} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} placeholder="64자리 소문자 16진수" onChange={(event) => setUpstreamSha(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">발행자 표시 권리 안내 (선택)<input className="input" aria-label="발행자 표시 권리 안내" value={upstreamLicence} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setUpstreamLicence(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">가져온 과정 기록 (선택)<input className="input" aria-label="원본 가져온 과정 기록" value={upstreamNote} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setUpstreamNote(event.target.value)} /></label>
          </div>
        </details>
        <details className="rounded-lg border border-line bg-sunk p-3 text-[12px]">
          <summary className="tap-target cursor-pointer font-semibold">내보내기 도구 (선택)</summary>
          <p className="mt-1 leading-5 text-ink-2">원본을 만든 재구성 소프트웨어가 아니라, 등록할 GeoTIFF를 내보낸 도구를 적으세요. 모르면 비워 두세요.</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 font-semibold">도구 이름<input className="input" aria-label="내보내기 도구 이름" value={exportToolName} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setExportToolName(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">도구 버전<input className="input" aria-label="내보내기 도구 버전" value={exportToolVersion} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setExportToolVersion(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">내보내기 설정 확인값 (선택)<input className="input" aria-label="내보내기 설정 확인값" value={exportSettingsDigest} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} placeholder="sha256:…" onChange={(event) => setExportSettingsDigest(event.target.value)} /></label>
            <label className="flex flex-col gap-1 font-semibold">내보내기 시각 (선택)<input className="input" aria-label="내보내기 시각 (한국 표준시)" type="datetime-local" step="1" value={exportedAtLocal} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} onChange={(event) => setExportedAtLocal(event.target.value)} /></label>
          </div>
          <label className="mt-2 flex flex-col gap-1 font-semibold">내보내기 기록 (선택)<input className="input" aria-label="내보내기 기록" value={exportNote} disabled={busy || hashing || formIsFrozen || !newIntentAllowed} maxLength={1000} onChange={(event) => setExportNote(event.target.value)} /></label>
        </details>
        </>}
        <FilePickerField
          label="정사영상 (선택)"
          ariaLabel="정사영상 GeoTIFF"
          accept=".tif,.tiff"
          disabled={busy || hashing || Boolean(frozenAttempt) || (!newIntentAllowed && !resume)}
          onSelect={(file) => void select("ortho", file ?? undefined)}
          selectedFileName={ortho?.file.name ?? null}
        />
        {ortho && headers.ortho && <ExternalHeaderRecognition slot="ortho" state={headers.ortho} crs={declaredCrs.ortho} crsLocked={busy || hashing || formIsFrozen || !newIntentAllowed} resumingRegistered={Boolean(resume)} onCrsChange={(value) => setDeclaredCrs((current) => ({ ...current, ortho: value }))} />}
        <FilePickerField
          label="DSM (선택)"
          ariaLabel="DSM GeoTIFF"
          accept=".tif,.tiff"
          disabled={busy || hashing || Boolean(frozenAttempt) || (!newIntentAllowed && !resume)}
          onSelect={(file) => void select("dsm", file ?? undefined)}
          selectedFileName={dsm?.file.name ?? null}
        />
        <p className="text-[12px] leading-5 text-ink-2">정사영상 또는 DSM 중 하나 이상을 선택하세요. 원본 사진은 요청하지 않습니다.</p>
        {dsm && headers.dsm && <ExternalHeaderRecognition slot="dsm" state={headers.dsm} crs={declaredCrs.dsm} crsLocked={busy || hashing || formIsFrozen || !newIntentAllowed} resumingRegistered={Boolean(resume)} onCrsChange={(value) => setDeclaredCrs((current) => ({ ...current, dsm: value }))} />}
        <p className="text-[12px] leading-5 text-ink-2">파일 이름은 영문·숫자로 시작하고 영문·숫자·밑줄(_)·점(.)·하이픈(-)만 쓸 수 있습니다(최대 255자). 원본 파일은 바꾸지 말고 조건에 맞는 이름의 복사본을 선택하세요. 이름을 자동으로 바꾸지는 않습니다.</p>
        {(["ortho", "dsm"] as const).map((kind) => {
          const issue = nameIssues[kind];
          if (!issue) return null;
          const keptName = kind === "ortho" ? ortho?.file.name ?? null : dsm?.file.name ?? null;
          const slotLabel = kind === "ortho" ? "정사영상" : "DSM";
          return <div key={kind} role="alert" className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">
            <p className="break-all">‘{issue.fileName}’ 파일은 등록할 수 없습니다. {issue.reason} 원본 파일은 바꾸지 말고, 조건에 맞는 이름의 복사본을 선택하세요.</p>
            {keptName
              ? <p className="mt-1">이전에 확인한 {slotLabel} 파일({keptName})은 그대로 두었습니다. 유효한 파일을 다시 선택하면 바뀌고, 지우면 비워집니다.</p>
              : <p className="mt-1">선택된 {slotLabel} 파일이 없습니다. 조건에 맞는 복사본을 다시 선택하세요.</p>}
            <button className="btn mt-2 w-fit" disabled={busy || hashing || Boolean(frozenAttempt)} onClick={() => clearSlot(kind)}>이전 선택 지우기</button>
          </div>;
        })}
        {newIntentAllowed && (resume || frozenAttempt) && <button className="btn w-fit" disabled={busy || hashing} onClick={startNewAttempt}>새로 등록하기</button>}
        {hashing && <p role="status" className="text-ink-2">파일 확인 중: {formatBytesKo(hashProgress ?? 0)}</p>}
        {hashing && <button className="btn w-fit" onClick={cancelHash}>파일 확인 취소</button>}
        <p className="text-ink-2">{ortho ? `정사영상 ${formatFileSize(ortho.size)} 확인 완료` : dsm ? "정사영상 미선택" : "등록할 파일(정사영상 또는 DSM)을 선택하세요."}{dsm ? ` · DSM ${formatFileSize(dsm.size)} 확인 완료` : ortho ? " · DSM 미선택" : ""}</p>
        {hasFile && !formIsFrozen && metadataIssue !== null && <p role="status" className="text-ink-2">{metadataIssue}</p>}
        {/* 서버 확인 계정이 없으면 새 쓰기를 보내지 않는다. 버튼 잠금과 함께
            이유를 밝혀 두되, 등록 자료·검사 상태 읽기는 그대로 둔다. */}
        {!formIsFrozen && !continuity && <p role="alert" className="text-[13px] text-high-ink">계정을 확인하지 못해 산출물 등록을 시작할 수 없습니다. 연결과 로그인 상태를 확인한 뒤 화면을 다시 여세요. 등록 자료와 검사 상태 확인은 계속할 수 있습니다.</p>}
        <button className="btn w-fit" disabled={!canSubmit} onClick={() => void submit()}>{busy ? "자료 등록 마무리 중" : sealedComplete ? "파일 제출 완료" : "자료 등록 마치기"}</button>
        <p className="text-[12px] leading-5 text-ink-2">마치면 파일 검사가 준비됩니다. 검증 완료를 뜻하지 않습니다. 등록은 검사·분석 승인이 아니며, 미상 정보가 있으면 이후 분석·비교 가능 여부는 별도로 확인합니다.</p>
        {uploadProgress && <p role="status" className="text-ink-2">{uploadProgress.artifactId === "ortho" ? "정사영상" : "DSM"} {uploadProgress.phase === "uploaded" ? "파일 전송 완료" : "파일 전송 중"}: {formatBytesKo(uploadProgress.transferredBytes)} / {formatBytesKo(uploadProgress.totalBytes)} {uploadProgress.phase === "uploading" && " · 전송 시간이나 비율은 추정하지 않습니다."}</p>}
        {busy && <p className="text-[12px] leading-5 text-ink-2">등록 중단은 이미 접수·전송된 내용을 되돌리지 않습니다. 중단 뒤 목록을 다시 읽어 실제 상태를 확인하세요.</p>}
        {busy && <button className="btn w-fit" onClick={cancelSubmission}>등록 중단</button>}
        {message && <p role={messageAlert ? "alert" : "status"} className="text-ink-2">{message}</p>}
      </div>
      </div>
    </details>
    </ResponsiveActionBoundary>}
    {listState === "ready" && revisions.length > 0 && <ul className="flex flex-col gap-2 text-ink-2">{revisions.map((revision) => {
      const key = inspectionKey(revision);
      const inspection = inspectionByRevision.get(key);
      const inspectionView = retainedInspectionView(inspection);
      const presentation = inspectionView !== null ? presentExternalInspectionStatus(inspectionView) : null;
      const display = inspectionView !== null && presentation?.displayReady === true
        && typeof inspectionView.display.sanitizedDisplayRef === "string" && typeof inspectionView.display.receiptDigest === "string"
        ? {
          sanitizedDisplayRef: inspectionView.display.sanitizedDisplayRef,
          receiptDigest: inspectionView.display.receiptDigest,
        }
        : null;
      const captureLine = describeCaptureLine(revision.submission.inputDeclaration as { captureBasis?: string | null; captureDate?: string | null; captureStartedAt?: string | null; captureEndedAt?: string | null } | null | undefined, (startedAt, endedAt) => `${formatKoreanDateTime(startedAt, { dateStyle: "short", timeStyle: "short" })} – ${formatKoreanDateTime(endedAt, { dateStyle: "short", timeStyle: "short" })}`);
      const producerLine = describeProducerLine(revision.submission.producerDeclaration);
      const retentionLine = describeRetentionLine(revision.submission.inputDeclaration);
      // V1/V2 기록의 행 표시는 그대로 둔다. 새 행 줄(제작·시점 선언)은 V3 표식이
      // 있을 때만 싣는다 — 실행 주체·장소 고정값(접수 정체성)을 재구성 실행
      // 사실처럼 읽히게 하지 않는다.
      const isV3Record = revision.submission.contractVersion === "external-reconstruction-submission.v3"
        || revision.submission.producerDeclaration?.producerKnowledge != null
        || revision.submission.inputDeclaration?.captureBasis != null;
      return <li key={key} className="rounded-lg border border-line px-3 py-2"><p>{describeArtifactKinds(revision.submission.artifacts)} · {formatRegistrationVersion(revision.submission.revision)} · {presentation?.title ?? (inspection?.phase === "error" ? "검사 상태를 불러오지 못했습니다." : "검사 상태 확인 중")}</p>
        {isV3Record && producerLine && <p className="mt-1 text-[12px] leading-5 text-ink-2">{producerLine}</p>}
        {isV3Record && captureLine && <p className="mt-1 text-[12px] leading-5 text-ink-2">{captureLine}</p>}
        {presentation && <><p className="mt-1 text-[12px] leading-5 text-ink-2">{presentation.detail}</p><p className="mt-1 text-[12px] leading-5 text-ink-muted">다음: {presentation.nextAction}</p>{presentation.artifactReasons.length > 0 && <ul className="mt-1 list-disc pl-5 text-[12px] leading-5 text-high-ink">{presentation.artifactReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}</>}
        {inspection?.phase === "loading" && inspectionView !== null && <p role="status" className="mt-1 text-[12px] text-ink-2">마지막으로 확인한 검사 상태를 유지한 채 업데이트를 확인하고 있습니다.</p>}
        {inspection?.phase === "error" && inspectionView !== null && <p role="alert" className="mt-1 text-[12px] text-high-ink">검사 상태 업데이트를 확인하지 못했습니다. 마지막으로 확인한 상태를 표시합니다. 새로고침으로 다시 시도하세요.</p>}
        {inspectionAutoRefreshStopped && presentation?.autoRefresh && <p role="status" className="mt-1 text-[12px] text-ink-2">자동 상태 확인을 멈췄습니다. 마지막으로 확인한 검사 상태를 표시합니다. 새로고침으로 다시 확인하세요.</p>}
        <div className="mt-2 flex flex-wrap gap-2"><button className="btn" onClick={() => { inspectionAutoRefreshBudget.current = 0; setInspectionAutoRefreshStopped(false); void loadInspection(revision); }}>검사 상태 새로고침</button>{display && <button className="btn" onClick={() => setVisibleDisplay((current) => current === key ? null : key)}>{visibleDisplay === key ? "표시용 정사영상 닫기" : "표시용 정사영상 열기"}</button>}{canWrite && revision.state === "REGISTERED" && <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" reason="등록 중인 외부 산출물을 다시 이어가는 일은 노트북 이상의 화면에서만 진행합니다."><button className="btn" onClick={() => selectResume(revision)}>등록 이어하기</button></ResponsiveActionBoundary>}</div>
        {display && visibleDisplay === key && <ExternalSanitizedOrthophoto workOrderId={workOrderId} submissionRef={revision.submissionRef} revision={revision.submission.revision} sanitizedDisplayRef={display.sanitizedDisplayRef} receiptDigest={display.receiptDigest} onDismiss={() => setVisibleDisplay(null)} />}
        <details className="mt-1 text-[12px] text-ink-2"><summary className="tap-target cursor-pointer">파일 정보 · 처리 상세</summary><div className="mt-1 break-all"><p>제출 상태: {submissionStateLabel(revision.state)} ({revision.state})</p><p>제출 식별자: {revision.submissionRef}</p>{producerLine && <p>{producerLine}</p>}{isV3Record && revision.submission.producerDeclaration?.sourceNote && <p>출처 기록: {revision.submission.producerDeclaration.sourceNote}</p>}{isV3Record && captureLine && <p>{captureLine}</p>}{isV3Record && retentionLine && <p>{retentionLine}</p>}{isV3Record && revision.submission.inputDeclaration?.upstreamSource && <><p>공개 출처 주소: {revision.submission.inputDeclaration.upstreamSource.sourceUri ?? "확인 필요"} (내려받거나 검증하지 않습니다)</p><p>공개 출처 확인값·권리·과정: {[revision.submission.inputDeclaration.upstreamSource.sourceSha256, revision.submission.inputDeclaration.upstreamSource.licenceDeclaration, revision.submission.inputDeclaration.upstreamSource.retrievalNote].filter((part) => typeof part === "string" && part.length > 0).join(" · ") || "신고 없음"}</p></>}{isV3Record && revision.submission.inputDeclaration?.derivativeExport && <p>내보내기 도구: {revision.submission.inputDeclaration.derivativeExport.toolName ?? "확인 필요"}{revision.submission.inputDeclaration.derivativeExport.toolVersion ? ` ${revision.submission.inputDeclaration.derivativeExport.toolVersion}` : ""} (재구성 소프트웨어와 다를 수 있음)</p>}{revision.submission.observationEpochId && <p>촬영 기록: {revision.submission.observationEpochId}</p>}{revision.submission.artifacts?.map((artifact) => <p key={artifact.artifactId}>산출물: {artifact.kind} · {artifact.fileName} · {artifact.declaredSizeBytes}바이트 · 확인값(해시) {artifact.declaredSha256}</p>)}{inspectionView !== null && <><p>검사 상태: {inspectionView.inspection.state}</p><p>표시 상태: {inspectionView.display.state}</p>{inspectionView.inspection.outcome?.map((outcome) => <p key={`${outcome.artifactId}:${outcome.outcome}:${outcome.reason ?? ""}`}>산출물 기록: {outcome.artifactId} · {outcome.outcome}{outcome.reason ? ` · 사유 코드/기록: ${outcome.reason}` : ""}</p>)}</>}</div></details>
      </li>;
    })}</ul>}
  </section>
  {/* 자식은 계속 마운트해 보존된 조회·시도 상태를 버리지 않는다. */}
  <details ref={legacyDetails} open={initialReport ? true : undefined} className="rounded-xl border border-line bg-sunk/40" aria-label="이전 비교 흐름 기록">
    <summary className="tap-target cursor-pointer px-4 py-3 text-[13px] font-bold text-ink-2">이전 비교 흐름(V1) · 검사점·물량·재관측</summary>
    <div className="flex flex-col gap-3 border-t border-line p-4">
      <p className="text-[12px] leading-5 text-ink-muted">이전 흐름의 기록 조회와 요청 기능입니다. 새 변화 분석과 결과 검토는 현장의 분석·검토에서 진행합니다.</p>
    <ExternalEvidencePanel workOrderId={workOrderId} siteId={siteId} revisions={revisions} canWrite={canWrite} newIntentAllowed={newIntentAllowed} accountIdentity={accountIdentity} legacyDecisionClosed={legacyDecisionClosed} onRelativeVolumeDecisionChange={receiveRelativeVolumeDecision} onSingleVolumeDecisionChange={receiveSingleVolumeDecision} />
    <ExternalResultWorkflowPanel workOrderId={workOrderId} siteId={siteId} decision={relativeVolumeDecision} singleVolumeDecision={singleVolumeDecision} initialReport={initialReport} permissions={permissions ?? (canWrite ? ["SITES_WRITE"] : [])} workAreaNames={workAreaNames} newIntentAllowed={newIntentAllowed} legacyDecisionClosed={legacyDecisionClosed} />
    </div>
  </details>
  </>;
}

export function ExternalReconstructionPanel(props: { workOrderId: string; siteId?: string; expectedEpochId: string | null; canWrite: boolean; permissions?: readonly string[]; initialReport?: TrustedExternalResultLink; requiresCaptureInterval?: boolean; newIntentAllowed?: boolean; workAreaNames?: Readonly<Record<string, string>>; accountIdentity?: { fingerprint: string } | null; legacyDecisionClosed?: boolean }) {
  return <ExternalReconstructionPanelState key={`${props.workOrderId}:${props.initialReport?.reportRef ?? ""}:${props.initialReport?.reportDigest ?? ""}`} {...props} />;
}
