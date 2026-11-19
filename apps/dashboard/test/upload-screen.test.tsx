/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => createElement("a", { href, ...props }, children),
}));

import { UploadScreen, type UploadScreenDeps } from "@/app/sites/[siteId]/upload/UploadScreen";
import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";
import type { GeoTiffRawHeader } from "@/lib/geo/geotiff-header";
import { inspectCandidate } from "@/lib/site-upload-files";
import { UploadFlowError, type UploadFlowEvent, type UploadFlowInput } from "@/lib/site-upload-flow";

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
  return render(<UploadScreen siteId="site-1" siteName="북측 현장" workAreas={[{ workAreaId: "wa-1", name: "북측 1차 구역", polygon }]} initialWorkAreaId={null} accountIdentity={accountIdentity} deps={deps} />);
}

function inspectionView({ outcome, reason = null, observedVerticalReference = null }: {
  outcome: "MEASURED" | "REJECTED";
  reason?: string | null;
  observedVerticalReference?: { identifier: string; basis: string } | null;
}): ExternalArtifactInspectionView {
  const reported = outcome === "MEASURED";
  const artifactOutcome = { artifactId: "dsm", outcome, reason };
  return {
    registrationState: "SEALED",
    sealState: "SEALED",
    inspection: {
      state: reported ? "INSPECTION_REPORTED" : "INSPECTION_FAILED_INCOMPLETE",
      phase: reported ? "COMPLETE" : "FAILED_INCOMPLETE",
      outcome: [artifactOutcome],
      request: null,
      report: reported ? {
        measurementPayload: {
          outcomes: [{
            ...artifactOutcome,
            measurements: { observedVerticalReference },
          }],
        },
      } : null,
    },
    display: { state: "NOT_REQUIRED", sanitizedDisplayRef: null, receiptDigest: null },
  } as ExternalArtifactInspectionView;
}

async function pick(files: File[]) {
  const input = screen.getByLabelText("자료 파일 고르기") as HTMLInputElement;
  await act(async () => { fireEvent.change(input, { target: { files } }); });
}

function inFolder(path: string): File {
  return Object.defineProperty(file(path.split("/").at(-1)!), "webkitRelativePath", { value: path });
}

async function pickFolder(files: File[]) {
  await act(async () => { fireEvent.change(screen.getByLabelText("결과 폴더 선택"), { target: { files } }); });
}

const fillTimes = () => {
  fireEvent.change(screen.getByLabelText("촬영 날짜"), { target: { value: "2024-10-10" } });
  fireEvent.change(screen.getByLabelText("촬영 시작 시각"), { target: { value: "09:20" } });
  fireEvent.change(screen.getByLabelText("촬영 종료 시각"), { target: { value: "10:05" } });
};
const upload = () => screen.getByRole("button", { name: /올리기|다시 시도/ });

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("UploadScreen", () => {
  it("waits for a survey choice and only inspects and registers that survey's two primary files", async () => {
    const inspect = vi.fn((f: File, id: string, polygon: Record<string, unknown> | null | undefined) =>
      inspectCandidate(f, id, polygon, { read: async () => f.name === "result.tif" ? orthoHeader : dsmHeader }));
    const { deps, runs } = makeDeps({ inspect });
    await mount(deps);
    const contents = (survey: string) => ["result.tif", "dsm.tif", "result_Red.tif", "gsddsm.tif", "tiles/tile.tif"]
      .map((name) => inFolder(`surveys/${survey}/terra/default/map/${name}`));
    const july = contents("07-05");
    await pickFolder([...contents("04-15"), ...july]);
    fillTimes();
    expect(inspect).not.toHaveBeenCalled();
    expect((upload() as HTMLButtonElement).disabled).toBe(true);
    const chooser = screen.getByRole("radiogroup", { name: "결과 폴더" });
    fireEvent.click(within(chooser).getByRole("radio", { name: /07-05/ }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "선택한 파일 사용" })); });
    expect(inspect.mock.calls.map(([f]) => f)).toEqual(july.slice(0, 2));
    expect(screen.getByText(/선택한 결과 폴더 · .*07-05/)).toBeTruthy();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    expect(runs).toHaveLength(0);
    await act(async () => { fireEvent.click(upload()); });
    expect(runs[0]!.files.map(({ fileName, producer }) => [fileName, producer])).toEqual([["result.tif", null], ["dsm.tif", null]]);
  });

  it("offers another choice after an unrelated folder and never hashes a misleading primary filename", async () => {
    const { deps } = makeDeps();
    const hash = vi.spyOn(deps, "hash");
    deps.inspect = (f, id, polygon) => inspectCandidate(f, id, polygon, { read: async () => dsmHeader });
    await mount(deps);
    await pickFolder([inFolder("survey/aerial/photo.tif")]);
    expect(screen.getByText(/정사영상이나 DSM을 찾지 못했습니다/)).toBeTruthy();
    const ortho = inFolder("survey/terra/default/map/result.tif");
    const dsm = inFolder("survey/terra/default/map/dsm.tif");
    await pickFolder([ortho, dsm]);
    expect(screen.getByText(/폴더에서 찾은 정사영상의 종류/)).toBeTruthy();
    expect(hash.mock.calls.map(([f]) => f)).toEqual([dsm]);
    expect(within(screen.getByRole("region", { name: "정사영상" })).getByText("아직 없음")).toBeTruthy();
  });

  it("lets the operator omit ambiguous mapper mosaics and use just the DSM", async () => {
    const { deps } = makeDeps();
    const inspect = vi.spyOn(deps, "inspect").mockImplementation((f, id, polygon) => inspectCandidate(f, id, polygon, { read: async () => dsmHeader }));
    await mount(deps);
    const dsm = inFolder("survey/3_dsm_ortho/1_dsm/survey_dsm.tif");
    await pickFolder([dsm, inFolder("survey/3_dsm_ortho/2_mosaic/survey_mosaic_group1.tif"),
      inFolder("survey/3_dsm_ortho/2_mosaic/survey_transparent_mosaic_group1.tif")]);
    expect(inspect).not.toHaveBeenCalled();
    const apply = screen.getByRole("button", { name: "선택한 파일 사용" }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.change(screen.getByRole("combobox", { name: "정사영상 파일" }), { target: { value: "skip" } });
    await act(async () => { fireEvent.click(apply); });
    expect(inspect.mock.calls.map(([f]) => f)).toEqual([dsm]);
    expect(screen.getByText(/선택한 결과 폴더 · PIX4Dmapper/)).toBeTruthy();
  });

  it("can cancel a large set of surveys without reading any file and continue with manual selection", async () => {
    const { deps } = makeDeps();
    const inspect = vi.spyOn(deps, "inspect");
    await mount(deps);
    await pickFolder(Array.from({ length: 6 }, (_, i) => inFolder(`survey/day-${i}/terra/default/map/dsm.tif`)));
    expect(screen.getByRole("combobox", { name: "결과 폴더" }).children).toHaveLength(7);
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(inspect).not.toHaveBeenCalled();
    expect(screen.queryByRole("combobox", { name: "결과 폴더" })).toBeNull();
    const manual = file("dsm.tif");
    await pick([manual]);
    expect(inspect.mock.calls.map(([f]) => f)).toEqual([manual]);
    expect(screen.queryByText(/선택한 결과 폴더/)).toBeNull();
  });

  it("keeps an unsupported mapper basename out of a new submission before hashing", async () => {
    const { deps, runs } = makeDeps();
    const hash = vi.spyOn(deps, "hash");
    deps.inspect = (f, id, polygon) => inspectCandidate(f, id, polygon, { read: async () => dsmHeader });
    await mount(deps);
    await pickFolder([inFolder("현장/3_dsm_ortho/1_dsm/농지_dsm.tif")]);
    expect(screen.getByText(/이름의 복사본을 고르세요/)).toBeTruthy();
    fillTimes();
    expect(hash).not.toHaveBeenCalled();
    expect((upload() as HTMLButtonElement).disabled).toBe(true);
    expect(runs).toHaveLength(0);
  });

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

  it("identifies the file omitted from the map and still allows both files to be uploaded", async () => {
    const { deps } = makeDeps({
      inspect: (f, id, polygon) => inspectCandidate(f, id, polygon, {
        read: async () => f.name === "dsm.tif" ? { ...dsmHeader, geoKeys: { ProjectedCSTypeGeoKey: 7850 } } : orthoHeader,
      }),
    });
    await mount(deps);
    await pick([file("ortho.tif"), file("dsm.tif")]);
    expect(await screen.findByText("DSM (높이) 파일의 범위를 지도에 표시할 수 없습니다.")).toBeTruthy();
    expect(screen.getByRole("img", { name: "작업구역 북측 1차 구역 위에 올릴 파일 정사영상의 범위" })).toBeTruthy();
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "DSM (높이) 파일 빼기" }));
    expect(screen.queryByText(/파일의 범위를 지도에 표시할 수 없습니다/)).toBeNull();
  });

  it("keeps a keyboard file picker in the remaining slot and waits for the second header before registering", async () => {
    const { deps, runs } = makeDeps();
    const inspect = deps.inspect;
    let finishHeader!: () => void;
    deps.inspect = async (...args) => {
      if (args[0].name === "ortho.tif") await new Promise<void>((resolve) => { finishHeader = resolve; });
      return inspect(...args);
    };
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    const picker = screen.getByLabelText("자료 파일 고르기") as HTMLInputElement;
    const click = vi.spyOn(picker, "click");
    fireEvent.click(within(screen.getByRole("region", { name: "정사영상" })).getByRole("button", { name: "파일 추가" }));
    expect(click).toHaveBeenCalledOnce();
    await pick([file("ortho.tif")]);
    expect(screen.getByRole("status").textContent).toContain("선택한 파일");
    expect((screen.getByRole("button", { name: "파일 확인 중…" }) as HTMLButtonElement).disabled).toBe(true);
    expect(runs).toHaveLength(0);
    await act(async () => { finishHeader(); });
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(runs[0]?.files.map(({ fileName }) => fileName)).toEqual(["ortho.tif", "dsm.tif"]);
  });

  it("shows which file is transferring, which one is queued, and when Core is sealing", async () => {
    const { deps } = makeDeps();
    let update!: (event: UploadFlowEvent) => void;
    let finish!: () => void;
    deps.createSession = () => ({
      async run(_signal, onEvent) {
        update = onEvent;
        await new Promise<void>((resolve) => { finish = resolve; });
        return { workOrderId: "wo-1", submissionRef: "ers-v1-ref", revision: 1 };
      },
    });
    await mount(deps);
    await pick([file("ortho.tif"), file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(upload());
    act(() => {
      update({ type: "stage", stage: "upload" });
      update({ type: "progress", kind: "ortho", transferredBytes: 0, totalBytes: 1234 });
    });
    const ortho = within(screen.getByRole("region", { name: "정사영상" }));
    const dsm = within(screen.getByRole("region", { name: "DSM (높이)" }));
    expect(ortho.getByText("전송 중")).toBeTruthy();
    expect(dsm.getByText("전송 대기")).toBeTruthy();
    act(() => {
      update({ type: "fileDone", kind: "ortho" });
      update({ type: "progress", kind: "dsm", transferredBytes: 0, totalBytes: 1234 });
    });
    expect(ortho.getByText("전송 완료")).toBeTruthy();
    expect(dsm.getByText("전송 중")).toBeTruthy();
    act(() => { update({ type: "fileDone", kind: "dsm" }); update({ type: "stage", stage: "seal" }); });
    expect(screen.getByRole("status").textContent).toContain("제출을 마무리");
    await act(async () => { finish(); });
  });

  it("explains a chip only when it is pressed", async () => {
    const { deps } = makeDeps();
    await mount(deps);
    await pick([file("dsm.tif")]);
    const chip = await screen.findByRole("button", { name: "높이 기준 없음" });
    expect(screen.queryByText(/파일에서 수직 기준/)).toBeNull();
    fireEvent.click(chip);
    expect(screen.getByText(/파일에서 수직 기준/)).toBeTruthy();
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

  it("cancels a long file check from its slot and allows the file to be selected again", async () => {
    let firstSignal: AbortSignal | undefined;
    let hashCalls = 0;
    const { deps } = makeDeps({
      hash: (f, signal) => {
        hashCalls += 1;
        if (hashCalls > 1) return Promise.resolve({ file: f, sha256: "a".repeat(64), size: f.size });
        firstSignal = signal;
        return new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
        });
      },
    });
    await mount(deps);
    await pick([file("dsm.tif")]);
    expect(await screen.findByRole("progressbar", { name: "DSM (높이) 확인 중" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "DSM (높이) 확인 취소" }));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "DSM (높이)" })).getByText("아직 없음")).toBeTruthy());
    expect(firstSignal?.aborted).toBe(true);

    await pick([file("dsm.tif")]);
    await waitFor(() => expect(screen.getByRole("button", { name: "DSM (높이) 파일 빼기" })).toBeTruthy());
    expect(hashCalls).toBe(2);
  });

  it("hands the hashed files, area and shooting window to the flow and shows the finished state", async () => {
    const { deps, runs, run } = makeDeps({ readInspection: async () => inspectionView({ outcome: "MEASURED" }) });
    await mount(deps);
    await pick([file("ortho.tif"), file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(run).toHaveBeenCalledTimes(1);
    expect(runs[0]).toMatchObject({ siteId: "site-1", workAreaId: "wa-1", workAreaName: "북측 1차 구역", continuity: `v1-${"e".repeat(64)}`, endedLocal: expect.stringMatching(/T10:05$/) });
    expect(runs[0]!.files.map((item) => [item.kind, item.sha256, item.declaredCrs])).toEqual([["ortho", "a".repeat(64), "EPSG:5186"], ["dsm", "a".repeat(64), "EPSG:5186"]]);
    expect(await screen.findByText("올리기가 끝났습니다")).toBeTruthy();
    expect(screen.getByText(/파일 검사에서 DSM의 높이 기준을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "자료에서 높이 기준 선택" }).getAttribute("href")).toBe("/sites/site-1/upload/open?workAreaId=wa-1&workOrderId=wo-1&submissionRef=ers-v1-ref&revision=1&artifactId=dsm");
  });

  it("opens the uploaded orthophoto when no DSM was uploaded", async () => {
    const { deps } = makeDeps();
    await mount(deps);
    await pick([file("ortho.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(await screen.findByText("올리기가 끝났습니다")).toBeTruthy();
    expect(screen.getByRole("link", { name: "자료 보기" }).getAttribute("href")).toMatch(/&artifactId=ortho$/);
  });

  it("offers a height-reference declaration only after Core measured a DSM without one", async () => {
    const { deps } = makeDeps({ readInspection: async () => inspectionView({ outcome: "MEASURED" }) });
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(await screen.findByText("DSM 파일 검사 완료")).toBeTruthy();
    expect(screen.getByText(/파일 검사에서 DSM의 높이 기준을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "자료에서 높이 기준 선택" })).toBeTruthy();
  });

  it("shows a Core rejection reason without treating the browser preflight as approval", async () => {
    const { deps } = makeDeps({ readInspection: async () => inspectionView({ outcome: "REJECTED", reason: "UNSUPPORTED_RASTER" }) });
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(await screen.findByText("파일 검사 불완료")).toBeTruthy();
    expect(screen.getByText(/DSM: 압축 방식, 색 방식, 밴드 구성/)).toBeTruthy();
    expect(screen.queryByText(/파일 검사에서 DSM의 높이 기준을 확인하지 못했습니다/)).toBeNull();
    expect(screen.getByRole("link", { name: "자료 보기" })).toBeTruthy();
  });

  it("distinguishes missing inspection status, bounds polling, and offers a manual recheck", async () => {
    const readInspection = vi.fn<UploadScreenDeps["readInspection"]>(async () => null);
    const { deps } = makeDeps({ readInspection });
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    vi.useFakeTimers();
    await act(async () => { fireEvent.click(upload()); });
    expect(screen.getByText("파일 업로드는 마쳤지만 검사 상태를 확인하지 못했습니다.")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(29 * 4_000); });
    expect(readInspection).toHaveBeenCalledTimes(30);
    expect(screen.getByText("파일 업로드는 마쳤지만 검사 상태를 확인하지 못했습니다.")).toBeTruthy();
    expect(screen.queryByText(/파일 검사에서 DSM의 높이 기준을 확인하지 못했습니다/)).toBeNull();
    expect(screen.getByText(/자동 확인을 마쳤습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "등록 상태 보기" }).getAttribute("href")).toBe("/field/work-orders/wo-1");

    readInspection.mockResolvedValueOnce(inspectionView({ outcome: "MEASURED" }));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "검사 상태 다시 확인" })); });
    expect(readInspection).toHaveBeenCalledTimes(31);
    expect(screen.getByText("DSM 파일 검사 완료")).toBeTruthy();
  });

  it("reads a newly issued inspection after policy admission without re-uploading the DSM", async () => {
    const measured = inspectionView({ outcome: "MEASURED" });
    const readInspection = vi.fn<UploadScreenDeps["readInspection"]>()
      .mockResolvedValueOnce({
        ...measured,
        inspection: { state: "INSPECTION_PENDING_POLICY", phase: null, outcome: null, request: null, report: null },
      })
      .mockResolvedValueOnce(measured);
    const { deps, run } = makeDeps({ readInspection });
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(screen.getByText("검사 기준 확인 필요")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "자료에서 높이 기준 선택" })).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "검사 상태 다시 확인" })); });
    expect(screen.getByText("DSM 파일 검사 완료")).toBeTruthy();
    expect(run).toHaveBeenCalledTimes(1);
    expect(readInspection.mock.calls[1]![0]).toEqual(readInspection.mock.calls[0]![0]);
  });

  it("aborts an inspection request when the completion screen closes and ignores its late response", async () => {
    let resolveInspection: ((view: ExternalArtifactInspectionView) => void) | undefined;
    let inspectionSignal: AbortSignal | undefined;
    const { deps } = makeDeps({
      readInspection: async (_result, signal) => {
        inspectionSignal = signal;
        return new Promise((resolve) => { resolveInspection = resolve; });
      },
    });
    const mounted = await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect(inspectionSignal?.aborted).toBe(false);
    mounted.unmount();
    expect(inspectionSignal?.aborted).toBe(true);
    await act(async () => { resolveInspection?.(inspectionView({ outcome: "MEASURED" })); });
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

  it("offers a same-revision retry after the server confirms an observation seal refusal", async () => {
    const { deps, runs, run } = makeDeps();
    run.mockRejectedValueOnce(new UploadFlowError(
      "seal", false,
      "서버 저장소에서 업로드한 파일을 찾지 못해 제출을 봉인하지 못했습니다. 같은 제출로 다시 시도하면 이 제출의 파일을 모두 다시 올립니다.",
      "wo-1", "OBSERVATION_MISSING", true,
    ));
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));

    await act(async () => { fireEvent.click(upload()); });
    expect(await screen.findByText(/서버 저장소에서 업로드한 파일을 찾지 못해/)).toBeTruthy();
    const retry = screen.getByRole("button", { name: "같은 등록 다시 전송" });
    expect((retry as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: "처음부터 새로 시작" })).toBeNull();

    await act(async () => { fireEvent.click(retry); });

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
    run.mockRejectedValueOnce(new UploadFlowError("register", false, "올린 내용이 등록 기준에 맞지 않아 접수되지 않았습니다.", "wo-1"));
    await mount(deps);
    await pick([file("dsm.tif")]);
    fillTimes();
    await waitFor(() => expect((upload() as HTMLButtonElement).disabled).toBe(false));
    await act(async () => { fireEvent.click(upload()); });
    expect((screen.getByRole("button", { name: "올리기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("link", { name: "기존 등록 작업 열기" }).getAttribute("href")).toBe("/field/work-orders/wo-1");
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
