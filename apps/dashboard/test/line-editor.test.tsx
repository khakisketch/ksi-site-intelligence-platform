/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push, refresh: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => createElement("a", { href, ...props }, children),
}));
// 지도는 실제 브라우저에서 확인한다. 여기서는 지도가 부모에게 거는 호출만 흉내 낸다.
vi.mock("@/app/sites/[siteId]/measurements/new/LineEditorMap", () => ({
  LineEditorMap: ({ vertices, sourceRing, disabled, onAdd, onMove }: { vertices: [number, number][]; sourceRing?: [number, number][] | null; disabled: boolean; onAdd: (v: [number, number]) => void; onMove: (i: number, v: [number, number]) => void }) => createElement("div", { "data-testid": "map", "data-disabled": String(disabled), "data-source-ring": sourceRing?.length ?? 0 },
    createElement("button", { type: "button", onClick: () => onAdd([127.0 + vertices.length * 0.001, 37.0]) }, "지도 누르기"),
    createElement("button", { type: "button", onClick: () => onMove(0, [127.5, 37.5]) }, "첫 점 끌기")),
}));

import { LineEditor, type LineEditorProps } from "@/app/sites/[siteId]/measurements/new/LineEditor";

const FEATURE_ID = `mf-${"1".repeat(32)}`;
const CREATED_FEATURE_ID = `mf-${"2".repeat(32)}`;
const REF_JOB_ID = `spj-${"1".repeat(32)}`;
const CUR_JOB_ID = `spj-${"3".repeat(32)}`;
const RING: [number, number][] = [[126.99, 36.99], [127.02, 36.99], [127.02, 37.01], [126.99, 37.01], [126.99, 36.99]];
const base: LineEditorProps = {
  siteId: "site-1", workAreaId: "area-1", areaName: "북측 작업구역", ring: RING,
  initialVertices: [], initialName: "", editing: null, convertedFromCrs: null,
  source: null, focusRing: null, returnHref: "/sites/site-1/measurements?workAreaId=area-1",
};
const fetchMock = vi.fn();
const reply = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const show = (overrides: Partial<LineEditorProps> = {}) => render(<LineEditor {...base} {...overrides} />);
const save = () => screen.getByRole("button", { name: /선 저장|새 개정으로 저장/ }) as HTMLButtonElement;
const click = (times = 1) => { for (let i = 0; i < times; i += 1) fireEvent.click(screen.getByRole("button", { name: "지도 누르기" })); };
const name = (value: string) => fireEvent.change(screen.getByLabelText("이름"), { target: { value } });

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  nav.push.mockReset();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("새 측정 선", () => {
  it("선택한 자료의 읽기 전용 정보와 돌아갈 주소를 보존한다", () => {
    const source = {
      assetRef: `ksa-v1-${"b".repeat(64)}`,
      fileName: "Bonggil_autumn.tif",
      captureDate: "2020-10-20",
      footprint: RING.slice(0, 4),
    };
    show({ source, focusRing: source.footprint, returnHref: `/sites/site-1/measurements?workAreaId=area-1&assetRef=${source.assetRef}` });
    const details = screen.getByRole("complementary", { name: "선택한 DSM" });
    expect(details.textContent).toContain("Bonggil_autumn.tif");
    expect(details.textContent).toContain("2020-10-20");
    expect(screen.getByTestId("map").getAttribute("data-source-ring")).toBe("4");
    expect(within(screen.getByRole("form", { name: "측정 선" })).getByRole("link", { name: "돌아가기" }).getAttribute("href"))
      .toBe(`/sites/site-1/measurements?workAreaId=area-1&assetRef=${source.assetRef}`);
  });

  it("점이 둘 이상이고 이름이 있어야 저장할 수 있고, 모자란 것을 말한다", () => {
    show();
    expect(save().disabled).toBe(true);
    const need = screen.getByRole("list", { name: "저장하려면" }).textContent ?? "";
    expect(need).toContain("두 점 이상");
    expect(need).toContain("선의 이름을 적으세요");
    click();
    expect(save().disabled).toBe(true);
    click();
    expect(save().disabled).toBe(true); // 이름이 없다
    name("북쪽 경사면");
    expect(save().disabled).toBe(false);
    expect(screen.queryByRole("list", { name: "저장하려면" })).toBeNull();
  });

  it("점 수와 지도 위 길이를 보인다", () => {
    show();
    click(3);
    const live = document.querySelector('[aria-live="polite"]')!.textContent ?? "";
    expect(live).toContain("점 3개");
    expect(live).toMatch(/약 \d+\.\d m/);
  });

  it("저장은 경위도 선을 한 번만 보내고 성공하면 저장한 선 화면으로 간다", async () => {
    fetchMock.mockResolvedValue(reply(201, { revision: { featureId: FEATURE_ID } }));
    show();
    click(2);
    name(" 북쪽 경사면 ");
    fireEvent.click(save());
    await waitFor(() => expect(nav.push).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/sites/site-1/work-areas/area-1/measurement-features");
    expect(JSON.parse(init.body as string)).toEqual({ workAreaId: "area-1", name: "북쪽 경사면", line: { crs: "EPSG:4326", vertices: [[127, 37], [127.001, 37]] } });
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toMatch(/^console-/);
    expect(nav.push).toHaveBeenCalledWith(`/sites/site-1/measurements?workAreaId=area-1&feature=${FEATURE_ID}`);
  });

  it("선택한 자료 주소를 선 저장 뒤 결과 화면까지 유지한다", async () => {
    fetchMock.mockResolvedValue(reply(201, { revision: { featureId: FEATURE_ID } }));
    const assetRef = `ksa-v1-${"b".repeat(64)}`;
    show({ returnHref: `/sites/site-1/measurements?workAreaId=area-1&assetRef=${assetRef}` });
    click(2);
    name("해안 단면");
    fireEvent.click(save());
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(
      `/sites/site-1/measurements?workAreaId=area-1&assetRef=${assetRef}&feature=${FEATURE_ID}`,
    ));
  });

  it("새 선을 취소하면 이전 선과 명시적으로 고른 단면으로 돌아간다", () => {
    const returnHref = `/sites/site-1/measurements?workAreaId=area-1&feature=${FEATURE_ID}&ref=${REF_JOB_ID}&cur=${CUR_JOB_ID}&comparison=saved-decision`;
    show({ returnHref });
    expect(within(screen.getByRole("form", { name: "측정 선" })).getByRole("link", { name: "돌아가기" }).getAttribute("href")).toBe(returnHref);
    expect(save().disabled).toBe(true);
  });

  it("새 선 저장 뒤에는 과거 선의 단면 선택을 새 선에 붙이지 않는다", async () => {
    fetchMock.mockResolvedValue(reply(201, { revision: { featureId: CREATED_FEATURE_ID } }));
    const assetRef = `ksa-v1-${"b".repeat(64)}`;
    show({ returnHref: `/sites/site-1/measurements?workAreaId=area-1&assetRef=${assetRef}&feature=${FEATURE_ID}&ref=${REF_JOB_ID}&cur=${CUR_JOB_ID}&comparison=saved-decision` });
    click(2);
    name("서쪽 단면");
    fireEvent.click(save());
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(
      `/sites/site-1/measurements?workAreaId=area-1&assetRef=${assetRef}&feature=${CREATED_FEATURE_ID}`,
    ));
  });

  it("두 번 제출해도 요청은 하나다", async () => {
    let release: (value: unknown) => void = () => undefined;
    fetchMock.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    show();
    click(2);
    name("선");
    const form = screen.getByRole("form", { name: "측정 선" });
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    release(reply(201, { revision: { featureId: FEATURE_ID } }));
    await waitFor(() => expect(nav.push).toHaveBeenCalled());
  });

  it("서버가 거부하면 이유를 말하고 이동하지 않는다", async () => {
    fetchMock.mockResolvedValue(reply(409, { code: "TOO_MANY_FEATURES" }));
    show();
    click(2);
    name("선");
    fireEvent.click(save());
    expect((await screen.findByRole("alert")).textContent).toContain("한도에 닿았습니다");
    expect(nav.push).not.toHaveBeenCalled();
  });

  it.each([
    [502, { message: "응답 형식 확인 중" }],
    [201, { revision: {} }],
  ])("저장 확인이 불완전하면 같은 초안을 같은 키로 다시 확인한다 (%i)", async (status, value) => {
    fetchMock.mockResolvedValueOnce(reply(Number(status), value))
      .mockResolvedValueOnce(reply(201, { revision: { featureId: CREATED_FEATURE_ID } }));
    show();
    click(2);
    name("재확인할 선");
    fireEvent.click(save());
    expect((await screen.findByRole("alert")).textContent).toContain("저장 응답을 확인하지 못했습니다");
    expect(nav.push).not.toHaveBeenCalled();
    fireEvent.click(save());
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/sites/site-1/measurements?workAreaId=area-1&feature=${CREATED_FEATURE_ID}`));
    expect(fetchMock.mock.calls).toHaveLength(2);
    expect(fetchMock.mock.calls[1]![1]).toEqual(fetchMock.mock.calls[0]![1]);
  });

  it("응답을 모르는 실패는 같은 키로 다시 시도하고, 거부를 받으면 새 키를 쓴다", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network"));
    fetchMock.mockResolvedValueOnce(reply(409, { code: "IDEMPOTENCY_CONFLICT" }));
    fetchMock.mockResolvedValueOnce(reply(201, { revision: { featureId: FEATURE_ID } }));
    show();
    click(2);
    name("선");
    fireEvent.click(save());
    expect((await screen.findByRole("alert")).textContent).toContain("응답을 확인하지 못했습니다");
    fireEvent.click(save());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const keys = () => fetchMock.mock.calls.map(([, init]) => (init as RequestInit & { headers: Record<string, string> }).headers["Idempotency-Key"]);
    expect(keys()[1]).toBe(keys()[0]);
    await screen.findByText(/같은 요청이 다른 내용으로/);
    fireEvent.click(save());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(keys()[2]).not.toBe(keys()[1]);
  });
});

describe("점 수 상한", () => {
  it("256개에서는 지도를 눌러도 점이 늘지 않는다", () => {
    const many: [number, number][] = Array.from({ length: 256 }, (_, i) => [127 + i * 1e-5, 37]);
    show({ initialVertices: many, initialName: "선" });
    click();
    expect(document.querySelector('[aria-live="polite"]')!.textContent).toContain("점 256개");
    expect(screen.queryByLabelText("257번 점 위도")).toBeNull();
    // 좌표로 추가해도 같다.
    fireEvent.change(screen.getByLabelText("추가할 점 위도"), { target: { value: "37.1" } });
    fireEvent.change(screen.getByLabelText("추가할 점 경도"), { target: { value: "127.1" } });
    fireEvent.click(screen.getByRole("button", { name: "추가" }));
    expect(screen.getByRole("alert").textContent).toContain("256개까지");
    expect(document.querySelector('[aria-live="polite"]')!.textContent).toContain("점 256개");
  });
});

describe("점 편집", () => {
  it("끌어서 옮기면 좌표 표가 바뀌고 되돌릴 수 있다", () => {
    show({ initialVertices: [[127, 37], [127.001, 37]] });
    fireEvent.click(screen.getByRole("button", { name: "첫 점 끌기" }));
    expect((screen.getByLabelText("1번 점 위도") as HTMLInputElement).value).toBe("37.5");
    expect((screen.getByLabelText("1번 점 경도") as HTMLInputElement).value).toBe("127.5");
    fireEvent.click(screen.getByRole("button", { name: "되돌리기" }));
    expect((screen.getByLabelText("1번 점 경도") as HTMLInputElement).value).toBe("127");
    expect((screen.getByRole("button", { name: "되돌리기" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("표에서 좌표를 고치면 그 점이 옮겨지고, 틀린 값은 이유를 말하며 저장을 막는다", () => {
    show({ initialVertices: [[127, 37], [127.001, 37]], initialName: "선" });
    expect(save().disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("2번 점 위도"), { target: { value: "37.0005" } });
    expect((screen.getByLabelText("2번 점 위도") as HTMLInputElement).value).toBe("37.0005");
    expect(save().disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("2번 점 위도"), { target: { value: "91" } });
    expect(screen.getByRole("alert").textContent).toContain("-90~90");
    expect(save().disabled).toBe(true);
    expect(screen.getByRole("list", { name: "저장하려면" }).textContent).toContain("올바르지 않은 점");
    fireEvent.change(screen.getByLabelText("2번 점 위도"), { target: { value: "37.0004" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(save().disabled).toBe(false);
  });

  it("점을 지우면 선이 다시 모자라고, 모두 지울 수 있다", () => {
    show({ initialVertices: [[127, 37], [127.001, 37]], initialName: "선" });
    fireEvent.click(screen.getByRole("button", { name: "2번 점 지우기" }));
    expect(save().disabled).toBe(true);
    expect(screen.queryByLabelText("2번 점 위도")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "모두 지우기" }));
    expect(screen.queryByLabelText("1번 점 위도")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "되돌리기" }));
    expect(screen.getByLabelText("1번 점 위도")).toBeTruthy();
  });

  it("좌표를 적어 점을 추가할 수 있고(키보드), 틀린 입력은 거부한다", () => {
    show();
    fireEvent.change(screen.getByLabelText("추가할 점 위도"), { target: { value: "abc" } });
    fireEvent.change(screen.getByLabelText("추가할 점 경도"), { target: { value: "127" } });
    fireEvent.click(screen.getByRole("button", { name: "추가" }));
    expect(screen.getByRole("alert").textContent).toContain("십진수가 아닙니다");
    expect(screen.queryByLabelText("1번 점 위도")).toBeNull();
    fireEvent.change(screen.getByLabelText("추가할 점 위도"), { target: { value: "37.1" } });
    fireEvent.click(screen.getByRole("button", { name: "추가" }));
    expect((screen.getByLabelText("1번 점 위도") as HTMLInputElement).value).toBe("37.1");
    expect((screen.getByLabelText("추가할 점 위도") as HTMLInputElement).value).toBe("");
  });
});

describe("작업구역과 경고", () => {
  it("구역 밖의 점이 있으면 알린다", () => {
    show({ initialVertices: [[127, 37], [128, 37]], initialName: "선" });
    expect(document.querySelector('[aria-live="polite"]')!.textContent).toContain("작업구역 밖에 있는 점이 1개");
  });
  it("구역 안이면 경고하지 않는다", () => {
    show({ initialVertices: [[127, 37], [127.001, 37]], initialName: "선" });
    expect(document.querySelector('[aria-live="polite"]')!.textContent).not.toContain("작업구역 밖");
  });
  it("구역 모양을 모르면 안에 있다고 말하지 않는다", () => {
    show({ ring: null, initialVertices: [[127, 37], [127.001, 37]], initialName: "선" });
    const text = document.querySelector('[aria-live="polite"]')!.textContent ?? "";
    expect(text).toContain("구역 안인지는 확인하지 않습니다");
    expect(text).not.toContain("작업구역 밖에 있는 점");
  });
});

describe("선 고치기(새 개정)", () => {
  const editing = { featureId: FEATURE_ID, revision: 2 };

  it("불러온 선과 이름으로 열고 새 개정임을 알리며, 본 개정 번호와 함께 저장한다", async () => {
    fetchMock.mockResolvedValue(reply(201, { revision: { featureId: FEATURE_ID } }));
    show({ editing, initialName: "북쪽 경사면", initialVertices: [[127, 37], [127.001, 37]] });
    expect(screen.getByRole("heading", { name: "측정 선 고치기" })).toBeTruthy();
    expect(screen.getByRole("note").textContent).toContain("새 개정으로 저장됩니다");
    expect(screen.getByRole("note").textContent).toContain("이미 읽은 단면은 이전 개정의 결과로 남고");
    fireEvent.change(screen.getByLabelText("2번 점 경도"), { target: { value: "127.002" } });
    fireEvent.click(save());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/sites/site-1/work-areas/area-1/measurement-features/${FEATURE_ID}/revisions`);
    expect(JSON.parse(init.body as string)).toEqual({ expectedRevision: 2, name: "북쪽 경사면", line: { crs: "EPSG:4326", vertices: [[127, 37], [127.002, 37]] } });
    expect(nav.push).toHaveBeenCalledWith(`/sites/site-1/measurements?workAreaId=area-1&feature=${FEATURE_ID}`);
  });

  it("다른 좌표계에서 바꿔 온 선이면 그 사실을 알린다", () => {
    show({ editing, initialName: "선", initialVertices: [[127, 37], [127.001, 37]], convertedFromCrs: "EPSG:5186" });
    expect(screen.getByRole("note").textContent).toContain("EPSG:5186로 저장되어 있어");
    expect(screen.getByRole("note").textContent).toContain("새 개정은 경위도 선이 됩니다");
  });

  it("다른 사람이 먼저 고쳤으면 덮어쓰지 않고 알린다", async () => {
    fetchMock.mockResolvedValue(reply(409, { code: "REVISION_CONFLICT" }));
    show({ editing, initialName: "선", initialVertices: [[127, 37], [127.001, 37]] });
    fireEvent.click(save());
    expect((await screen.findByRole("alert")).textContent).toContain("다른 사람이 먼저 이 선을 고쳤습니다");
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("돌아가기는 고치던 선을 가리킨다", () => {
    show({ editing, initialName: "선", initialVertices: [[127, 37], [127.001, 37]], returnHref: `/sites/site-1/measurements?workAreaId=area-1&feature=${FEATURE_ID}` });
    expect(within(screen.getByRole("form", { name: "측정 선" })).getByRole("link", { name: "돌아가기" }).getAttribute("href")).toBe(`/sites/site-1/measurements?workAreaId=area-1&feature=${FEATURE_ID}`);
  });
});
