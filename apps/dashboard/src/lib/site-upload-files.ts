import { coverageOfArea, fileFootprintWgs84, type AreaCoverage, type FileFootprint } from "@/lib/geo/geotiff-footprint";
import {
  readGeoTiffHeader,
  recognizeGeoTiffHeader,
  type ArtifactSlot,
  type GeoTiffRawHeader,
  type GeoTiffRecognition,
} from "@/lib/geo/geotiff-header";
import { preflightGeoTiff, type PreflightFinding } from "@/lib/geo/geotiff-preflight";
import { assignSlots } from "@/lib/external-file-routing";

/**
 * 한 화면 올리기에서 파일을 고른 직후 하는 일: 머리말만 읽어 종류·범위·점검 결과를 만든다.
 * 픽셀은 읽지 않고 파일은 브라우저 밖으로 나가지 않는다. 이 결과는 안내일 뿐 판정이 아니며,
 * 최종 판정은 올린 뒤 Core 검사만 만든다. 읽지 못한 사실은 지어내지 않고 null로 둔다.
 */

export type UploadCandidate = {
  id: string;
  file: File;
  /** 파일이 가리키는 종류. 헤더가 분명히 말하지 않으면 null. */
  kind: ArtifactSlot | null;
  /** 폴더의 파일 배치가 가리키는 종류. 헤더와 일치할 때만 자동 선택한다. */
  expectedKind?: ArtifactSlot;
  readable: boolean;
  header: GeoTiffRawHeader | null;
  recognition: GeoTiffRecognition | null;
  findings: PreflightFinding[];
  footprint: FileFootprint | null;
  coverage: AreaCoverage | null;
};

export type HeaderReader = (file: File, signal?: AbortSignal) => Promise<GeoTiffRawHeader>;

export async function inspectCandidate(
  file: File,
  id: string,
  areaPolygon: Record<string, unknown> | null | undefined,
  options: { signal?: AbortSignal; read?: HeaderReader } = {},
): Promise<UploadCandidate> {
  const read = options.read ?? readGeoTiffHeader;
  let header: GeoTiffRawHeader;
  try {
    header = await read(file, options.signal);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { id, file, kind: null, readable: false, header: null, recognition: null, findings: [], footprint: null, coverage: null };
  }
  const recognition = recognizeGeoTiffHeader(header);
  const kind = recognition.kindHint;
  const footprint = fileFootprintWgs84(header);
  return {
    id,
    file,
    kind,
    readable: true,
    header,
    recognition,
    findings: kind ? preflightGeoTiff(kind, header, file.size) : [],
    footprint,
    coverage: footprint ? coverageOfArea(footprint, areaPolygon) : null,
  };
}

export type SlotAssignment = {
  ortho: UploadCandidate | null;
  dsm: UploadCandidate | null;
  skipped: { id: string; name: string; reason: string }[];
};

/** 고른 파일들을 정사영상·DSM 칸에 나눈다. 칸은 헤더가 분명히 가리킬 때만 정한다(이름으로 추측하지 않는다). */
export function assignCandidates(candidates: readonly UploadCandidate[]): SlotAssignment {
  const routing = assignSlots(candidates.map((candidate) => ({ name: candidate.file.name, hint: candidate.kind, readable: candidate.readable, expectedKind: candidate.expectedKind })), "simple");
  return {
    ortho: routing.assigned.ortho !== undefined ? candidates[routing.assigned.ortho]! : null,
    dsm: routing.assigned.dsm !== undefined ? candidates[routing.assigned.dsm]! : null,
    skipped: routing.skipped.map((item) => ({ id: candidates[item.index]!.id, name: item.name, reason: item.reason })),
  };
}

export type ChipTone = "ok" | "warn" | "block";
export type UploadChip = { key: string; tone: ChipTone; label: string; detail: string | null };

const COVERAGE_CHIP: Record<AreaCoverage, UploadChip> = {
  covers: { key: "coverage", tone: "ok", label: "구역을 덮음", detail: null },
  partial: { key: "coverage", tone: "warn", label: "구역 일부만", detail: "이 파일이 선택한 작업구역의 일부만 덮습니다. 분석은 겹친 부분만 읽을 수 있습니다." },
  disjoint: { key: "coverage", tone: "warn", label: "구역과 안 겹침", detail: "이 파일의 범위가 선택한 작업구역과 겹치지 않습니다. 다른 구역을 고르거나 파일을 확인하세요." },
};

/**
 * 파일 카드에 붙이는 짧은 칩. 확실한 거부 조건만 "거부 예상", 파일 안쪽을 봐야 아는 것은 "거부될 수 있음"으로 나눈다.
 * 칩은 길게 설명하지 않고, 설명(detail)은 누를 때만 보인다.
 */
export function chipsOf(candidate: UploadCandidate): UploadChip[] {
  const chips: UploadChip[] = [];
  const blocked = candidate.findings.filter((finding) => finding.level === "blocked");
  const may = candidate.findings.filter((finding) => finding.level === "may");
  const describe = (items: readonly PreflightFinding[]) => items.map((item) => (item.fix ? `${item.title} ${item.fix}` : item.title)).join("\n");
  if (candidate.coverage) chips.push(COVERAGE_CHIP[candidate.coverage]);
  const crs = candidate.recognition?.declaredCrs ?? null;
  const crsIssue = candidate.findings.find(({ code }) => code === "DSM_GEOGRAPHIC" || code === "GEOCENTRIC_CRS" || code === "CRS_NOT_ANALYSIS");
  if (crsIssue) {
    const label = crsIssue.code === "CRS_NOT_ANALYSIS" ? "분석 좌표계 아님" : [crs, "투영 좌표계 필요"].filter(Boolean).join(" · ");
    chips.push({ key: "crs", tone: crsIssue.level === "blocked" ? "block" : "warn", label, detail: describe([crsIssue]) });
  } else if (crs) {
    chips.push({ key: "crs", tone: "ok", label: crs, detail: null });
  }
  const vertical = candidate.findings.find((finding) => finding.code === "NO_VERTICAL_REFERENCE");
  if (vertical) chips.push({ key: "vertical", tone: "warn", label: "높이 기준 없음", detail: vertical.title });
  if (blocked.length > 0) chips.push({ key: "blocked", tone: "block", label: `거부 예상 ${blocked.length}`, detail: describe(blocked) });
  if (may.length > 0) chips.push({ key: "may", tone: "warn", label: `거부될 수 있음 ${may.length}`, detail: describe(may) });
  if (candidate.readable && candidate.kind && blocked.length === 0 && may.length === 0) {
    chips.push({ key: "preflight", tone: "ok", label: "거부 예상 없음", detail: "브라우저에서 파일 앞부분만 읽은 결과입니다. 최종 판정은 올린 뒤 KSI 검사가 합니다." });
  }
  return chips;
}
