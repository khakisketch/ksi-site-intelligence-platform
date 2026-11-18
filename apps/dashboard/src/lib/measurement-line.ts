/**
 * 측정 선을 그리는 쪽의 순수 규칙. 지도 그림과 키보드 입력이 같은 규칙을 쓴다.
 *
 * 선은 지도에서 그린 그대로 경위도(EPSG:4326, [경도, 위도])로 저장한다. 격자 좌표계로의 변환은 Core가
 * 읽을 때 하며, 여기서는 아무것도 추정하거나 맞추지 않는다. 저장은 위치만 기억하고 어떤 자료도 읽지 않는다.
 */

/** [경도, 위도]. Core 계약의 EPSG:4326 꼭짓점 순서와 같다. */
export type LineVertex = [number, number];

export const LINE_CRS = "EPSG:4326";
export const MIN_LINE_VERTICES = 2;
/** Core 계약의 표현 상한과 같다. */
export const MAX_LINE_VERTICES = 256;
export const MAX_LINE_NAME = 255;

const EARTH_RADIUS_M = 6_371_008.8;

/** 지도에서 누른 좌표를 센티미터 아래 자릿수에서 정리한다(같은 선이 같은 값으로 저장되게). */
export function roundCoordinate(value: number): number {
  return Math.round(value * 1e7) / 1e7;
}

export function roundVertex(vertex: LineVertex): LineVertex {
  return [roundCoordinate(vertex[0]), roundCoordinate(vertex[1])];
}

function validCoordinate(vertex: LineVertex): boolean {
  const [lon, lat] = vertex;
  return Number.isFinite(lon) && Number.isFinite(lat) && lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90;
}

function distinctCount(vertices: readonly LineVertex[]): number {
  return new Set(vertices.map(([lon, lat]) => `${lon},${lat}`)).size;
}

/** 저장을 막는 이유. 비어 있으면 저장할 수 있다. */
export function lineIssues(vertices: readonly LineVertex[]): string[] {
  const issues: string[] = [];
  if (vertices.length < MIN_LINE_VERTICES) issues.push("지도에서 두 점 이상을 눌러 선을 그리세요.");
  if (vertices.length > MAX_LINE_VERTICES) issues.push(`점은 ${MAX_LINE_VERTICES}개까지 둘 수 있습니다.`);
  if (vertices.some((vertex) => !validCoordinate(vertex))) issues.push("위도·경도 범위를 벗어난 점이 있습니다.");
  else if (vertices.length >= MIN_LINE_VERTICES && distinctCount(vertices) < MIN_LINE_VERTICES) issues.push("서로 다른 두 점이 있어야 선이 됩니다.");
  return issues;
}

/** 지도 위 대략 거리(m). 구면 근사이며 Core가 격자 좌표계에서 다시 재는 값과 조금 다를 수 있다. */
export function approxLengthM(vertices: readonly LineVertex[]): number {
  let total = 0;
  for (let index = 1; index < vertices.length; index += 1) {
    const [lon1, lat1] = vertices[index - 1]!;
    const [lon2, lat2] = vertices[index]!;
    const phi1 = (lat1 * Math.PI) / 180;
    const phi2 = (lat2 * Math.PI) / 180;
    const dPhi = phi2 - phi1;
    const dLambda = ((lon2 - lon1) * Math.PI) / 180;
    const a = Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
    total += 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
  }
  return total;
}

/** 경위도 점이 고리(닫힌 폴리곤 바깥 경계) 안에 있는가. 경계 위의 점은 안으로 본다. */
export function pointInRing(point: LineVertex, ring: readonly LineVertex[]): boolean {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    const onSegment = (x - xi) * (yj - yi) === (y - yi) * (xj - xi)
      && x >= Math.min(xi, xj) && x <= Math.max(xi, xj) && y >= Math.min(yi, yj) && y <= Math.max(yi, yj);
    if (onSegment) return true;
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** 작업구역 밖에 있는 점의 수. 구역 모양을 모르면 null이다(안에 있다고 말하지 않는다). */
export function outsideAreaCount(vertices: readonly LineVertex[], ring: readonly LineVertex[] | null): number | null {
  if (ring === null || ring.length < 3) return null;
  return vertices.filter((vertex) => !pointInRing(vertex, ring)).length;
}

export function insertVertex(vertices: readonly LineVertex[], index: number, vertex: LineVertex): LineVertex[] {
  const at = Math.max(0, Math.min(vertices.length, index));
  return [...vertices.slice(0, at), roundVertex(vertex), ...vertices.slice(at)];
}

export function moveVertex(vertices: readonly LineVertex[], index: number, vertex: LineVertex): LineVertex[] {
  if (index < 0 || index >= vertices.length) return [...vertices];
  return vertices.map((current, position) => (position === index ? roundVertex(vertex) : current));
}

export function removeVertex(vertices: readonly LineVertex[], index: number): LineVertex[] {
  if (index < 0 || index >= vertices.length) return [...vertices];
  return vertices.filter((_, position) => position !== index);
}

export interface VertexRow {
  lat: string;
  lon: string;
}

export function verticesToRows(vertices: readonly LineVertex[]): VertexRow[] {
  return vertices.map(([lon, lat]) => ({ lat: String(lat), lon: String(lon) }));
}

const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

function parseCoordinate(text: string, axis: "lat" | "lon"): { ok: true; value: number } | { ok: false; reason: string } {
  const label = axis === "lat" ? "위도" : "경도";
  const trimmed = text.trim();
  if (trimmed === "") return { ok: false, reason: `${label}를 입력하세요.` };
  // Number()는 "0x10" 같은 문자열도 읽는다. 십진수 모양만 받는다.
  if (!DECIMAL.test(trimmed)) return { ok: false, reason: `${label} "${trimmed}"은 십진수가 아닙니다.` };
  const value = Number(trimmed);
  const limit = axis === "lat" ? 90 : 180;
  if (!Number.isFinite(value) || value < -limit || value > limit) {
    return { ok: false, reason: `${label}는 -${limit}~${limit} 범위여야 합니다.` };
  }
  return { ok: true, value };
}

/** 키보드로 적은 위도·경도 줄을 점으로 읽는다. 틀린 줄은 몇 번째인지 알린다. */
export function rowsToVertices(rows: readonly VertexRow[]): { ok: true; vertices: LineVertex[] } | { ok: false; reason: string; rowIndex: number } {
  const vertices: LineVertex[] = [];
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index]!;
    const lat = parseCoordinate(row.lat, "lat");
    if (!lat.ok) return { ok: false, reason: `${index + 1}번째 줄: ${lat.reason}`, rowIndex: index };
    const lon = parseCoordinate(row.lon, "lon");
    if (!lon.ok) return { ok: false, reason: `${index + 1}번째 줄: ${lon.reason}`, rowIndex: index };
    vertices.push(roundVertex([lon.value, lat.value]));
  }
  return { ok: true, vertices };
}

export function lineNameIssue(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed === "") return "선의 이름을 적으세요.";
  if (trimmed.length > MAX_LINE_NAME) return `이름은 ${MAX_LINE_NAME}자까지입니다.`;
  return null;
}

export interface CreateLineBody {
  workAreaId: string;
  name: string;
  line: { crs: typeof LINE_CRS; vertices: LineVertex[] };
}

export interface ReviseLineBody {
  expectedRevision: number;
  name: string;
  line: { crs: typeof LINE_CRS; vertices: LineVertex[] };
}

export function createLineBody(workAreaId: string, name: string, vertices: readonly LineVertex[]): CreateLineBody {
  return { workAreaId, name: name.trim(), line: { crs: LINE_CRS, vertices: vertices.map(roundVertex) } };
}

export function reviseLineBody(expectedRevision: number, name: string, vertices: readonly LineVertex[]): ReviseLineBody {
  return { expectedRevision, name: name.trim(), line: { crs: LINE_CRS, vertices: vertices.map(roundVertex) } };
}

const KOREA_CRS = new Set(["EPSG:5179", "EPSG:5185", "EPSG:5186", "EPSG:5187", "EPSG:5188"]);

/**
 * 저장된 선을 편집기에 올릴 경위도로 바꾼다. 경위도로 저장된 선은 그대로, 한국 투영좌표계의 선은 같은 정의로
 * 변환한다. 그 밖의 좌표계는 모른다고 답한다(다른 좌표를 지어내지 않는다). 변환 뒤 저장하면 새 개정은 경위도 선이 된다.
 */
export function savedLineToEditorVertices(
  line: { crs: string; vertices: readonly (readonly [number, number])[] },
  project: (crs: string, vertex: readonly [number, number]) => [number, number],
): { ok: true; vertices: LineVertex[]; converted: boolean } | { ok: false; reason: string } {
  const code = line.crs.trim().toUpperCase();
  if (code === LINE_CRS) return { ok: true, vertices: line.vertices.map(([lon, lat]) => roundVertex([lon, lat])), converted: false };
  if (!KOREA_CRS.has(code)) return { ok: false, reason: `좌표계 ${line.crs}의 선은 이 화면에서 고칠 수 없습니다.` };
  const vertices = line.vertices.map((vertex) => roundVertex(project(code, vertex)));
  if (vertices.some((vertex) => !validCoordinate(vertex))) return { ok: false, reason: "선의 좌표를 지도 좌표로 바꾸지 못했습니다." };
  return { ok: true, vertices, converted: true };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseLine(value: unknown): { crs: typeof LINE_CRS; vertices: LineVertex[] } | null {
  if (!isRecord(value) || Object.keys(value).some((key) => key !== "crs" && key !== "vertices")) return null;
  if (value.crs !== LINE_CRS || !Array.isArray(value.vertices)) return null;
  const vertices: LineVertex[] = [];
  for (const item of value.vertices) {
    if (!Array.isArray(item) || item.length !== 2 || typeof item[0] !== "number" || typeof item[1] !== "number") return null;
    vertices.push([item[0], item[1]]);
  }
  return lineIssues(vertices).length === 0 ? { crs: LINE_CRS, vertices } : null;
}

/** 브라우저가 보낸 저장 본문의 형식 검사. 맞지 않으면 null이며 Core에 보내지 않는다. */
export function parseCreateLineBody(value: unknown): CreateLineBody | null {
  if (!isRecord(value) || Object.keys(value).some((key) => !["workAreaId", "name", "line"].includes(key))) return null;
  if (typeof value.workAreaId !== "string" || typeof value.name !== "string" || lineNameIssue(value.name) !== null) return null;
  const line = parseLine(value.line);
  return line === null ? null : { workAreaId: value.workAreaId, name: value.name.trim(), line };
}

export function parseReviseLineBody(value: unknown): ReviseLineBody | null {
  if (!isRecord(value) || Object.keys(value).some((key) => !["expectedRevision", "name", "line"].includes(key))) return null;
  if (!Number.isSafeInteger(value.expectedRevision) || (value.expectedRevision as number) < 1 || (value.expectedRevision as number) > 100) return null;
  if (typeof value.name !== "string" || lineNameIssue(value.name) !== null) return null;
  const line = parseLine(value.line);
  return line === null ? null : { expectedRevision: value.expectedRevision as number, name: value.name.trim(), line };
}
