import {
  seoulDateTimeLocalToUtc,
  type ExternalArtifactKind,
  type ExternalV3CaptureBasis,
  type ExternalV3ProducerKnowledge,
  type ExternalV3RetentionLocus,
} from "@/lib/external-reconstruction-submission";

/**
 * 현장 화면의 "작업 없는 한 화면 올리기"가 V3 등록 BFF로 보내는 신고서.
 *
 * 사용자가 입력하는 것은 촬영 시작·종료 시각뿐이다. 나머지는 파일 머리말이 알려 준 사실만 쓰고,
 * 모르는 값은 모른다고 기록한다 — 이름·버전·보관 위치를 지어내지 않는다. 날짜만 아는 경우나
 * 시점 미상은 이 화면이 받지 않는다(그런 자료는 두 시점 비교에서 빠지므로 기존 등록 화면에서 다룬다).
 */

export type SimpleUploadFile = {
  kind: ExternalArtifactKind;
  fileName: string;
  sha256: string;
  size: number;
  /** 헤더에서 읽은 좌표계. 읽지 못했으면 null(신고하지 않는다). */
  declaredCrs: string | null;
  /** 헤더의 Software 태그에서 읽은 제작 소프트웨어. */
  producer: { name: string; version: string | null } | null;
};

export type SimpleUploadBody = {
  submissionId: string;
  expectedEpochId: string;
  submittedAt: string;
  producerKnowledge: ExternalV3ProducerKnowledge;
  softwareName: string | null;
  softwareVersion: string | null;
  sourceNote: null;
  captureBasis: ExternalV3CaptureBasis;
  captureStartedAt: string;
  captureEndedAt: string;
  captureDate: null;
  originalRetentionLocus: ExternalV3RetentionLocus;
  originalRetentionDetail: null;
  upstreamSource: null;
  derivativeExport: null;
  artifacts: readonly {
    artifactId: ExternalArtifactKind;
    kind: ExternalArtifactKind;
    fileName: string;
    format: "GeoTIFF";
    contentType: "application/octet-stream";
    declaredSha256: string;
    declaredSizeBytes: number;
    declaredCrs: string | null;
    declaredVerticalReference: null;
    declaredGsdM: null;
  }[];
};

/** 시작·종료 입력(한국 표준시 `YYYY-MM-DDTHH:mm`)에 문제가 있으면 한 줄 사유, 없으면 null. */
export function captureWindowIssue(startedLocal: string, endedLocal: string): string | null {
  const started = seoulDateTimeLocalToUtc(startedLocal);
  const ended = seoulDateTimeLocalToUtc(endedLocal);
  if (started === null || ended === null) return "촬영 시작과 종료 시각을 모두 입력하세요.";
  if (!(Date.parse(ended) > Date.parse(started))) return "종료 시각이 시작보다 늦어야 합니다.";
  if (Date.parse(ended) > Date.now() + 5 * 60 * 1000) return "종료 시각이 미래입니다. 다시 확인하세요.";
  return null;
}

/** 신고서는 제작 소프트웨어가 하나이므로 포함한 모든 파일의 머리말이 일치해야 한다. */
function producerOf(files: readonly SimpleUploadFile[]): Pick<SimpleUploadBody, "producerKnowledge" | "softwareName" | "softwareVersion"> {
  if (files.some((file) => file.producer === null)) {
    return { producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null };
  }

  const producers = files.flatMap(({ producer }) => producer
    ? [{ name: producer.name.trim(), version: producer.version?.trim() ?? "" }]
    : []);
  const names = [...new Set(producers.map(({ name }) => name))];
  if (names.length !== 1 || names[0] === "") {
    return { producerKnowledge: "UNKNOWN", softwareName: null, softwareVersion: null };
  }

  const versions = [...new Set(producers.map(({ version }) => version).filter(Boolean))];
  if (versions.length !== 1 || producers.some(({ version }) => version === "")) {
    return { producerKnowledge: "PARTIAL", softwareName: names[0]!, softwareVersion: null };
  }
  return { producerKnowledge: "DECLARED", softwareName: names[0]!, softwareVersion: versions[0]! };
}

export type BuildResult = { ok: true; body: SimpleUploadBody } | { ok: false; reason: string };

export function buildSimpleUploadBody(input: {
  submissionId: string;
  expectedEpochId: string;
  submittedAt: string;
  startedLocal: string;
  endedLocal: string;
  files: readonly SimpleUploadFile[];
}): BuildResult {
  const issue = captureWindowIssue(input.startedLocal, input.endedLocal);
  if (issue) return { ok: false, reason: issue };
  if (input.files.length === 0 || input.files.length > 2) return { ok: false, reason: "정사영상이나 DSM을 하나 이상 고르세요." };
  const kinds = input.files.map((file) => file.kind);
  if (new Set(kinds).size !== kinds.length) return { ok: false, reason: "같은 종류의 파일이 둘 이상입니다." };
  return {
    ok: true,
    body: {
      submissionId: input.submissionId,
      expectedEpochId: input.expectedEpochId,
      submittedAt: input.submittedAt,
      ...producerOf(input.files),
      sourceNote: null,
      captureBasis: "EXACT_INTERVAL",
      captureStartedAt: seoulDateTimeLocalToUtc(input.startedLocal)!,
      captureEndedAt: seoulDateTimeLocalToUtc(input.endedLocal)!,
      captureDate: null,
      originalRetentionLocus: "unknown",
      originalRetentionDetail: null,
      upstreamSource: null,
      derivativeExport: null,
      artifacts: input.files.map((file) => ({
        artifactId: file.kind,
        kind: file.kind,
        fileName: file.fileName,
        format: "GeoTIFF" as const,
        contentType: "application/octet-stream" as const,
        declaredSha256: file.sha256,
        declaredSizeBytes: file.size,
        declaredCrs: file.declaredCrs,
        declaredVerticalReference: null,
        declaredGsdM: null,
      })),
    },
  };
}
