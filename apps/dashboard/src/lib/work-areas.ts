import type { Tone } from "@/lib/core-api/labels";
import type { AoiVertex, WorkArea } from "@/lib/core-api/types";

/**
 * 작업구역 화면의 **순수 판정**(M4-C) — 렌더링에서 떼어내 테스트 가능하게 둔다.
 *
 * 여기 서버 판정을 복제하지 않는다. 등록 가부(폴리곤 모양·개수 상한·대체 대상)는
 * 전부 Core 가 정하고(`work_areas.py`), 이 파일이 하는 일은 **이미 등록된 것을
 * 화면으로 옮기는 것**뿐이다 — 상태로 두 칸을 가르고, 굳어 버린 기하를 지도가
 * 다룰 수 있는 꼴로 되돌린다.
 */

export const WORK_AREA_STATUS_LABEL: Record<
  WorkArea["status"],
  { label: string; tone: Tone; description: string }
> = {
  ACTIVE: {
    label: "사용 중",
    tone: "positive",
    description: "이후 비교에서 이 구역을 고를 수 있습니다.",
  },
  ARCHIVED: {
    label: "보관됨",
    tone: "neutral",
    description:
      "새 비교에서는 더 이상 고를 수 없습니다 — 이미 이 구역으로 낸 리포트는 그대로 남습니다.",
  },
};

/**
 * 등록된 폴리곤(GeoJSON)을 지도가 다루는 꼭짓점으로 되돌린다 — `toZonePolygon` 의 역.
 *
 * **좌표 순서가 이 함수의 존재 이유다.** GeoJSON 은 경도·위도 순이고 지도는
 * 위도·경도(`AoiVertex`)로 다룬다 — 뒤집으면 "다시 그리기" 폼이 지구 반대편
 * 폴리곤을 초기값으로 띄우고, 사용자는 그걸 고쳐 그려 등록하게 된다.
 *
 * 링의 마지막 점은 첫 점과 같다(GeoJSON 이 요구하는 닫힘) — 되돌릴 때 한 번 연다.
 * 그러지 않으면 다시 그릴 때마다 같은 자리 꼭짓점이 하나씩 늘어난다.
 *
 * 서버가 준 폴리곤은 `Record<string, unknown>` 이라 모양을 신뢰할 수 없다. 한 점이라도
 * 읽어낼 수 없으면 빈 배열이고, 호출부는 그때 "지도에 옮기지 못했다"로 다룬다 —
 * 반쯤 읽은 좌표로 폴리곤을 만들면 사용자가 **엉뚱한 범위를 고쳐 그려 등록**한다.
 */
export function polygonToVertices(
  polygon: Record<string, unknown> | null | undefined,
): AoiVertex[] {
  const ring = (polygon as { coordinates?: unknown[] } | null | undefined)?.coordinates?.[0];
  if (!Array.isArray(ring)) return [];

  const vertices: AoiVertex[] = [];
  for (const point of ring) {
    if (!Array.isArray(point) || point.length < 2) return [];
    const [lonDeg, latDeg] = point as unknown[];
    if (typeof lonDeg !== "number" || typeof latDeg !== "number") return [];
    vertices.push({ latDeg, lonDeg });
  }

  const first = vertices[0];
  const last = vertices[vertices.length - 1];
  if (vertices.length >= 2 && first.latDeg === last.latDeg && first.lonDeg === last.lonDeg) {
    vertices.pop();
  }
  return vertices;
}

/**
 * 고를 수 있는 것과 지나간 것을 가른다 — 한 목록에 섞어 놓으면 보관된 구역을
 * 고르려 들고, 그 시도는 서버까지 갔다가 `WORK_AREA_UNUSABLE` 로 돌아온다.
 *
 * 정렬(최신 등록이 위)은 화면이 정하는 것이다 — 서버 응답 순서에 기대지 않는다.
 */
export function partitionWorkAreas(workAreas: readonly WorkArea[]): {
  active: WorkArea[];
  archived: WorkArea[];
} {
  const newestFirst = [...workAreas].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return {
    active: newestFirst.filter((area) => area.status === "ACTIVE"),
    archived: newestFirst.filter((area) => area.status === "ARCHIVED"),
  };
}
