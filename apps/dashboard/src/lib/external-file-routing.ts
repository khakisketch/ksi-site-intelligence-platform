import type { ArtifactSlot } from "@/lib/geo/geotiff-header";

/**
 * 한 번에 고른 여러 파일을 정사영상/DSM 칸에 나눈다. 칸은 파일 헤더가 분명히 가리킬 때만 정한다
 * (단일 실수 밴드 → DSM, 8비트 3~4밴드 → 정사영상). 파일 이름으로 추측하지 않는다.
 * 정할 수 없거나 같은 칸에 둘 이상 들어오는 파일은 옮기지 않고 이유와 함께 돌려준다.
 */

export type RoutingCandidate = { name: string; hint: ArtifactSlot | null; readable: boolean };

export type RoutingResult = {
  /** 칸 → 입력 목록에서의 위치. */
  assigned: Partial<Record<ArtifactSlot, number>>;
  skipped: { index: number; name: string; reason: string }[];
};

const SLOT_LABEL: Record<ArtifactSlot, string> = { ortho: "정사영상", dsm: "DSM" };

export function isTiffName(name: string): boolean {
  return /\.tiff?$/i.test(name);
}

export function assignSlots(candidates: readonly RoutingCandidate[]): RoutingResult {
  const assigned: RoutingResult["assigned"] = {};
  const skipped: RoutingResult["skipped"] = [];
  candidates.forEach((candidate, index) => {
    if (!isTiffName(candidate.name)) {
      skipped.push({ index, name: candidate.name, reason: "GeoTIFF(.tif, .tiff) 파일만 올릴 수 있습니다." });
      return;
    }
    if (!candidate.readable) {
      skipped.push({ index, name: candidate.name, reason: "GeoTIFF 헤더를 읽지 못했습니다. 올바른 파일인지 확인하세요." });
      return;
    }
    if (candidate.hint === null) {
      skipped.push({ index, name: candidate.name, reason: "정사영상인지 DSM인지 파일에서 알 수 없습니다. 아래 칸에서 직접 선택하세요." });
      return;
    }
    if (assigned[candidate.hint] !== undefined) {
      skipped.push({ index, name: candidate.name, reason: `${SLOT_LABEL[candidate.hint]}로 보이는 파일이 둘 이상입니다. 한 번에 ${SLOT_LABEL[candidate.hint]} 하나만 올릴 수 있어 먼저 고른 파일만 넣었습니다.` });
      return;
    }
    assigned[candidate.hint] = index;
  });
  return { assigned, skipped };
}
