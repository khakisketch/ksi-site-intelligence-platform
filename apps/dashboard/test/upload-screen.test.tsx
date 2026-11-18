/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => createElement("a", { href, ...props }, children),
}));

import { UploadScreen, type UploadScreenDeps } from "@/app/sites/[siteId]/upload/UploadScreen";
import type { GeoTiffRawHeader } from "@/lib/geo/geotiff-header";
import { inspectCandidate } from "@/lib/site-upload-files";
import { UploadFlowError, type UploadFlowInput } from "@/lib/site-upload-flow";

const layout = {
  compression: 8, predictor: 1, photometric: 1, planarConfiguration: 1, extraSamples: [], hasNoDataTag: true, scale: null, offset: null,
  georeferenced: true, modelType: 1, projLinearUnits: 9001, verticalCsType: null, verticalUnits: null,
};
const dsmHeader: GeoTiffRawHeader = {
  width: 100, height: 100, samplesPerPixel: 1, bitsPerSample: 32, sampleFormat: 3, geoKeys: { ProjectedCSTypeGeoKey: 5186 },
  software: null, dateTime: null, pixelSize: [1, 1], boundingBox: [200000, 550000, 201000, 551000], layout,
};
const orthoHeader: GeoTiffRawHeader = { ...dsmHeader, samplesPerPixel: 3, bitsPerSample: 8, sampleFormat: 1, layout: { ...layout, photometric: 2 } };

// 구역은 DSM 범위의 한가운데 작은 사각형이다(계산 결과를 시험이 직접 알 수 있게 파일 범위에서 뽑는다).
async function areaAround(): Promise<Record<string, unknown>> {
  const probe = await inspectCandidate(new File([new Uint8Array(1)], "p.tif"), "p", null, { read: async () => dsmHeader });
  const [lon, lat] = probe.footprint!.ring.reduce((acc, [x, y]) => [acc[0]! + x / 4, acc[1]! + y / 4], [0, 0]) as [number, number];
  const h = 0.0004;
  return { type: "Polygon", coordinates: [[[lon - h, lat - h], [lon + h, lat - h], [lon + h, lat + h], [lon - h, lat + h], [lon - h, lat - h]]] };
}

const headers: Record<string, GeoTiffRawHeader> = { "dsm.tif": dsmHeader, "ortho.tif": orthoHeader };
const file = (name: string, size = 1234) => Object.defineProperty(new File([new Uint8Array(1)], name), "size", { value: size }) as File;

function makeDeps(overrides: Partial<UploadScreenDeps> = {}) {
  const runs: UploadFlowInput[] = [];
  const run = vi.fn(async () => ({ workOrderId: "wo-1", submissionRef: "ers-v1-ref", revision: 1 }));
  const deps: UploadScreenDeps = {
    inspect: (f, id, polygon) => inspectCandidate(f, id, polygon, { read: async () => { const header = headers[f.name]; if (!header) throw new Error("not tiff"); return header; } }),
    hash: async (f) => ({ file: f, sha256: "a".repeat(64), size: f.size }),
    createSession: (input) => { runs.push(input); return { run }; },
    readInspection: async () => null,
    ...overrides,
  };
  return { deps, runs, run };
}

async function mount(deps: UploadScreenDeps, accountIdentity: { fingerprint: string } | null = { fingerprint: `v1-${"e".repeat(64)}` }) {
  const polygon = await areaAround();
  render(<UploadScreen siteId="site-1" siteName="북측 현장" workAreas={[{ workAreaId: "wa-1", name: "북측 1차 구역", polygon }]} initialWorkAreaId={null} accountIdentity={accountIdentity} deps={deps} />);
}

async function pick(files: File[]) {
  const input = screen.getByLabelText("자료 파일 고르기") as HTMLInputElement;
  await act(async () => { fireEvent.change(input, { target: { files } }); });
}

const fillTimes = () => {
  fireEvent.change(screen.getByLabelText("촬영 시작 시각"), { target: { value: "09:20" } });
  fireEvent.change(screen.getByLabelText("촬영 종료 시각"), { target: { value: "10:05" } });
};
const upload = () => screen.getByRole("button", { name: /올리기|다시 시도/ });

afterEach(() => cleanup());

describe("UploadScreen", () => {
  it("starts empty with a disabled upload button and a drop prompt", async () => {
    const { deps } = makeDeps();
    await mount(deps);
    expect(screen.getByText("정사영상·DSM을 여기에 놓기")).toBeTruthy();
    expect((screen.getByRole("button", { name: "올리기" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("puts picked files into the slots the headers point at and shows short chips", async () => {
    const { deps } = makeDeps();
    await mount(deps);
    await pick([file("ortho.tif"), file("dsm.tif")]);
    const dsmCard = await screen.findByRole("region", { name: "DSM (높이)" });
    expect(within(dsmCard).getByText(/dsm\.tif/)).toBeTruthy();
    expect(within(dsmCard).getByText("구역을 덮음")).toBeTruthy();
    expect(within(dsmCard).getByText("EPSG:5186")).toBeTruthy();
    expect(within(dsmCard).getByText("높이 기준 없음")).toBeTruthy();
    const orthoCard = screen.getByRole("region", { name: "정사영상" });
    expect(within(orthoCard).getByText(/ortho\.tif/)).toBeTruthy();
    expect(screen.getByRole("img", { name: /작업구역 북측 1차 구역 위에 올릴 파일 정사영상, DSM \(높이\)의 범위/ })).toBeTruthy();
  });

  it("explains a chip only when it is pressed", async () => {
    const { deps } = makeDeps();
    await mount(deps);
    await pick([file("dsm.tif")]);
    const chip = await screen.findByRole("button", { name: "높이 기준 없음" });
    expect(screen.queryByText(/파일에 수직 기준/)).toBeNull();
    fireEvent.click(chip);
    expect(screen.getByText(/파일에 수직 기준/)).toBeTruthy();
  });

  it("keeps files it cannot place out of the slots and says why", async () => {
    const { deps } = makeDeps();
    await mount(deps);
    await pick([file("dsm.tif"), file("photo.jpg")]);
    expect(await screen.findByText(/GeoTIFF\(\.tif, \.tiff\) 파일만/)).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "정사영상" })).getByText("아직 없음")).toBeTruthy();
  });

  it("enables upload only after files are checked and a valid shooting window is entered", async () => {
    const { deps } = makeDeps();
    await mount(deps);
    await pick([file("dsm.tif")]);
    await waitFor(() => expect(screen.queryByText(/파일 확인 중/)).toBeNull());
    expect((upload() as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("촬영 시작 시각"), { target: { value: "10:05" } });
    fireEvent.change(screen.getByLabelText("촬영 종료 시각"), { target: { value: "09:20" } });
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect((upload() as HTMLButtonElement).disabled).toBe(true);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
  });

  it("keeps upload disabled while the file is still being checked", async () => {
    let finish: (() => void) | undefined;
    const { deps } = makeDeps({ hash: (f) => new Promise((resolve) => { finish = () => resolve({ file: f, sha256: "a".repeat(64), size: f.size }); }) });
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    expect(await screen.findByRole("progressbar", { name: "DSM (높이) 확인 중" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "파일 확인 중…" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { finish?.(); });
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
  });

  it("hands the hashed files, area and shooting window to the flow and shows the finished state", async () => {
    const { deps, runs, run } = makeDeps();
    await mount(deps);
    await pick([file("ortho.tif"), file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(run).toHaveBeenCalledTimes(1);
    expect(runs[0]).toMatchObject({ siteId: "site-1", workAreaId: "wa-1", workAreaName: "북측 1차 구역", continuity: `v1-${"e".repeat(64)}`, endedLocal: expect.stringMatching(/T10:05$/) });
    expect(runs[0]!.files.map((item) => [item.kind, item.sha256, item.declaredCrs])).toEqual([["ortho", "a".repeat(64), "EPSG:5186"], ["dsm", "a".repeat(64), "EPSG:5186"]]);
    expect(await screen.findByText("올리기가 끝났습니다")).toBeTruthy();
    expect(screen.getByText(/DSM에 높이 기준이 없습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "자료에서 높이 기준 선택" }).getAttribute("href")).toBe("/sites/site-1/materials?workAreaId=wa-1");
  });

  it("retries the same session after an ambiguous failure instead of starting a new one", async () => {
    const { deps, runs, run } = makeDeps();
    run.mockRejectedValueOnce(new UploadFlowError("register", true, "응답을 확인하지 못했습니다. 다시 시도하면 같은 요청으로 이어서 확인합니다."));
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "처음부터 새로 시작" })).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "같은 요청으로 다시 시도" })); });
    expect(runs).toHaveLength(1);
    expect(run).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("올리기가 끝났습니다")).toBeTruthy();
  });

  it("locks files and the shooting window once a request has started so a retry cannot drift from what is shown", async () => {
    const { deps, run } = makeDeps();
    run.mockRejectedValueOnce(new UploadFlowError("register", true, "응답을 확인하지 못했습니다. 다시 시도하면 같은 요청으로 이어서 확인합니다."));
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    expect(screen.getByRole("button", { name: "DSM (높이) 파일 빼기" })).toBeTruthy();
    await act(async () => { fireEvent.click(upload()); });
    await screen.findByText(/응답을 확인하지 못했습니다/);
    expect(screen.queryByRole("button", { name: "DSM (높이) 파일 빼기" })).toBeNull();
    expect(screen.getByLabelText("촬영 종료 시각").matches(":disabled")).toBe(true);
    await pick([file("ortho.tif")]);
    expect(within(screen.getByRole("region", { name: "정사영상" })).getByText("아직 없음")).toBeTruthy();
  });

  it("starts a fresh session only after the server definitely refused", async () => {
    const { deps, runs, run } = makeDeps();
    run.mockRejectedValueOnce(new UploadFlowError("register", false, "올린 내용이 등록 기준에 맞지 않아 접수되지 않았습니다."));
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    await act(async () => { fireEvent.click(await screen.findByRole("button", { name: "처음부터 새로 시작" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "올리기" })); });
    expect(runs).toHaveLength(2);
  });

  it("does not offer upload without a verified account", async () => {
    const { deps } = makeDeps();
    await mount(deps, null);
    await pick([file("dsm.tif")]);
    fillTimes();
    expect(await screen.findByText(/계정을 확인하지 못해 올릴 수 없습니다/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /올리기|확인 중/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("lets the user take a file out before uploading", async () => {
    const { deps } = makeDeps();
    await mount(deps);
    await pick([file("dsm.tif")]);
    fireEvent.click(await screen.findByRole("button", { name: "DSM (높이) 파일 빼기" }));
    expect(within(screen.getByRole("region", { name: "DSM (높이)" })).getByText("아직 없음")).toBeTruthy();
  });
});
