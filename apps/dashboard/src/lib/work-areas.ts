import type { Tone } from "@/lib/core-api/labels";
import type { AoiVertex, WorkArea } from "@/lib/core-api/types";

/**
 * BFF 계정 연속성 가드의 거부 코드 — `@/lib/core-api/work-order-continuity`의
 * `ACCOUNT_CONTINUITY_MISMATCH` 와 같은 값이어야 한다. 공유 파일을 직접
 * import하지 않는 이유: 이 모듈은 클라이언트 패널도 import하므로 server-only인
 * 공유 파일을 끌어올 수 없다. 일치는 `work-area-submit-outcome.test.ts`의
 * pin 테스트가 고정한다.
 */
const ACCOUNT_CONTINUITY_MISMATCH_CODE = "ACCOUNT_CONTINUITY_MISMATCH";

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
 * 작업구역 POST 결과의 정직한 3분류 — **같은 키 재시도가 없는 경로의 전제**다.
 *
 * Core `work_areas.register` 는 호출마다 새 sequence 구역을 만든다(멱등 키 없음).
 * 그래서 브라우저가 응답을 잃으면 그 요청이 서버에 닿았는지 알 수 없고, 같은
 * 내용을 다시 보내면 구역이 두 개 생길 수 있다. 이 함수는 그 셋을 가른다:
 *
 * - `success`: 2xx + 본문의 구역이 **이 요청에 대한 답**일 때뿐이다. 같은 요청
 *   Site 일치 + 식별자·필수 필드 판독 + 보낸 원본(name·crs·polygon·supersedes)과
 *   응답의 일치가 모두 확인돼야 한다. 이름·기하 매칭 추정이 아니라, 응답이 보낸
 *   요청을 그대로 돌려줬다는 대조가 성공 근거다.
 * - `definiteFailure`: 서버가 이 요청을 쓰기 전에 거부했음이 **증명된** 응답뿐이다.
 *   BFF 로컬(400)·인증/인가(401/403)·범위(404)·요청 검증(422), 그리고 Core가
 *   journal append 전에 돌려주는 409 4종 verdict만 해당한다. 503을 포함한 모든
 *   5xx, 408/429, 알 수 없는 4xx 코드는 프록시·BFF·upstream이 Core commit 뒤에
 *   유실한 것일 수 있어 unknown이다 — 코드가 있다는 이유만으로 '쓰기 안 됨'을
 *   단정하지 않는다.
 * - `unknown`: 만들었을지 모른다. 자동 성공·같은 키 재시도 주장·이름/기하 매칭
 *   단정을 모두 금지하고, 읽기 전용 목록 확인 + 명시적 새 요청 선택으로만 푼다.
 */
export type WorkAreaSubmitOutcome =
  | { kind: "success"; workArea: WorkArea }
  | { kind: "definiteFailure"; code: string | null }
  | { kind: "unknown" };

/** 등록 거부 중 쓰기 전에 끝났음이 증명된 409 verdict — journal append 이전 반환. */
const DEFINITIVE_PREWRITE_409 = new Set([
  "SUPERSEDES_OTHER_SITE",
  "SUPERSEDES_NOT_ACTIVE",
  "ALREADY_ARCHIVED",
  "TOO_MANY_ACTIVE",
]);

function readBodyCode(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const verdict = (body as { verdict?: unknown }).verdict;
  const code = (body as { code?: unknown }).code;
  if (typeof verdict === "string" && verdict !== "") return verdict;
  if (typeof code === "string" && code !== "") return code;
  return null;
}

/** 명시적 새 요청이 보낸 원본 — 2xx 응답이 이 요청에 대한 답인지 대조한다. */
export interface WorkAreaSubmitRequest {
  name: string;
  crs: string;
  polygon: unknown;
  supersedes: string | null;
}

/**
 * 본문의 구역이 **이 요청에 대한 답**인지 검증한다. 다음이 모두 맞아야 한다:
 * `siteId` 일치·식별자 존재·필수 필드 판독·보낸 원본(name·crs·polygon·supersedes)과
 * 응답의 일치·fresh 등록 상태(ACTIVE)·등록 verdict(REGISTERED).
 *
 * Core `register` 는 요청 값을 그대로 저장해 돌려주므로(register 본체가 검증·append
 * 전에 값을 바꾸지 않는다), 하나라도 다르면 이 응답은 보낸 요청의 결과가 아니다 —
 * `{}`·다른 현장 ID·바뀐 이름·다른 기하·ARCHIVED·엉뚱한 verdict의 2xx는 모두
 * unknown이다. JSON 직렬화를 거친 polygon은 키 순서까지 보존되므로 문자열 대조가
 * 유효하고, 서버 정규화로 달라졌다면 그 또한 "다른 답"이므로 불명으로 두는 것이
 * 안전 방향이다.
 */
function validWorkAreaForRequest(
  body: unknown,
  siteId: string,
  request: WorkAreaSubmitRequest,
): WorkArea | null {
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.verdict === "string" && record.verdict !== "REGISTERED") return null;
  const workArea = record.workArea;
  // 화면 계약(정렬 localeCompare·렌더에 쓰는 필드)과 요청 Site를 먼저 만족해야
  // 한다 — 목록 검증과 같은 기준이다. createdAt 누락 등은 여기서 걸린다.
  if (!isReadableWorkArea(workArea, siteId)) return null;
  const area = workArea as Record<string, unknown>;
  // fresh 등록은 ACTIVE다. ARCHIVED가 돌아오면 이 요청에 대한 답이 아니다.
  if (area.status !== "ACTIVE") return null;
  // 보낸 원본과의 대조 — 응답이 다른 요청·다른 값에 대한 답이면 성공이 아니다.
  if (area.name !== request.name) return null;
  if (area.crs !== request.crs) return null;
  if (area.supersedes !== request.supersedes) return null;
  if (JSON.stringify(area.polygon) !== JSON.stringify(request.polygon)) return null;
  return workArea as WorkArea;
}

export function classifyWorkAreaSubmitOutcome(input: {
  /** `fetch` 자체가 던졌는가 — 응답 상태 자체가 없다. */
  fetchThrew: boolean;
  /** 응답 상태. `fetchThrew`면 null. */
  status: number | null;
  /** 파싱된 응답 본문(읽기 실패면 null). */
  body: unknown;
  /** 요청한 현장 ID — 성공 identity 검증의 기준. */
  siteId: string;
  /** 보낸 원본 — 2xx 응답이 이 요청에 대한 답인지 대조한다. */
  request: WorkAreaSubmitRequest;
}): WorkAreaSubmitOutcome {
  if (input.fetchThrew || input.status === null) {
    return { kind: "unknown" };
  }
  const { status, siteId, request } = input;
  const code = readBodyCode(input.body);
  if (status >= 200 && status < 300) {
    const workArea = validWorkAreaForRequest(input.body, siteId, request);
    return workArea !== null ? { kind: "success", workArea } : { kind: "unknown" };
  }
  // BFF 로컬 파싱 실패(400)·인증/인가(401/403)·범위(404)·요청 검증(422)은
  // 쓰기 전에 끝난 것이 증명된다 — 모두 journal 이전에 반환되는 경로다.
  if (status === 400 || status === 401 || status === 403 || status === 404) {
    return { kind: "definiteFailure", code };
  }
  if (status === 422) return { kind: "definiteFailure", code };
  // 409는 Core가 append 전에 돌려주는 4종 verdict일 때만 확정이다. 다른 코드의
  // 409는 이 경로가 낼 수 없는 응답이므로 출처를 단정할 수 없다.
  if (status === 409 && code !== null && DEFINITIVE_PREWRITE_409.has(code)) {
    return { kind: "definiteFailure", code };
  }
  // BFF 계정 연속성 가드가 Core 호출 전에 끊었으므로 이 요청은 쓰지 않았다 —
  // 다만 첫 불명은 여전히 미확인이므로 패널은 남긴다. 공유 파일의 상수와 같은
  // 값임이 pin 테스트로 고정된다.
  if (status === 409 && code === ACCOUNT_CONTINUITY_MISMATCH_CODE) {
    return { kind: "definiteFailure", code };
  }
  // 503 STORE_UNAVAILABLE도 Core commit 뒤 upstream 유실과 구별할 수 없으므로
  // 확정하지 않는다 — 코드가 있다는 이유만으로 '쓰기 안 됨'을 주장하지 않는다.
  // 408/429·그 밖의 4xx/5xx·알 수 없는 상태도 모두 unknown이다.
  return { kind: "unknown" };
}

/**
 * 목록 본문이 그 현장의 읽을 수 있는 `WorkArea[]`인지 검증한다 — 화면은 각 항목의
 * `createdAt`(정렬)·`status`·`name`·`polygon`·`crs`·`supersedes`까지 읽으므로,
 * ID·site만 맞고 나머지가 깨진 항목이 그대로 들어오면 화면이 터진다. 항목 하나라도
 * 계약에 어긋나면(다른 현장 ID 포함) 전체를 불명으로 둔다 — 틀린 목록으로는 화면을
 * 갱신하지 않고 이전 상태를 보존한다.
 */
export function parseWorkAreaList(body: unknown, siteId: string): WorkArea[] | null {
  if (typeof body !== "object" || body === null) return null;
  const workAreas = (body as { workAreas?: unknown }).workAreas;
  if (!Array.isArray(workAreas)) return null;
  for (const item of workAreas) {
    if (!isReadableWorkArea(item, siteId)) return null;
  }
  return workAreas as WorkArea[];
}

/** 화면이 실제로 읽는 필드까지 계약대로 있는지 확인한다. */
function isReadableWorkArea(item: unknown, siteId: string): boolean {
  if (typeof item !== "object" || item === null) return false;
  const area = item as Record<string, unknown>;
  if (typeof area.workAreaId !== "string" || area.workAreaId === "") return false;
  if (area.siteId !== siteId) return false;
  if (typeof area.name !== "string" || area.name === "") return false;
  if (typeof area.crs !== "string" || area.crs === "") return false;
  if (typeof area.polygon !== "object" || area.polygon === null) return false;
  if (area.status !== "ACTIVE" && area.status !== "ARCHIVED") return false;
  if (typeof area.createdAt !== "string" || area.createdAt === "") return false;
  if (area.supersedes !== null && typeof area.supersedes !== "string") return false;
  return true;
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
