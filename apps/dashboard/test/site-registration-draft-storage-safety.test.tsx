/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
vi.mock("@/components/map/AoiPolygonMap", () => ({ AoiPolygonMap: () => null }));

import { SiteRegistrationOnlyWizard } from "@/app/sites/new/SiteRegistrationOnlyWizard";

const KEY = "ksi-wizard-site-registration-only";
const IDENTITY = `v1-${"a".repeat(64)}`;
const NAME_PLACEHOLDER = "예: OO산업단지 3공구 신축공사 현장";

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ fingerprint: IDENTITY }), { status: 200 }),
  ));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("현장 등록 저장 초안 보호", () => {
  it("구 초안의 반출 선택만 남아도 주체 미상으로 잠그고 편집으로 귀속하지 않는다", async () => {
    const raw = JSON.stringify({ name: "", siteId: "", aoi: [], egressChoice: "allow" });
    sessionStorage.setItem(KEY, raw);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    await waitFor(() => expect(screen.queryByPlaceholderText(NAME_PLACEHOLDER) || screen.queryByText("주인을 확인할 수 없는 입력입니다")).toBeTruthy());
    // 기존 결함에서는 B가 이름을 편집할 수 있고 선택값까지 B에게 저장된다.
    const exposed = screen.queryByPlaceholderText(NAME_PLACEHOLDER);
    if (exposed) {
      fireEvent.change(exposed, { target: { value: "B edit" } });
      await waitFor(() => expect(JSON.parse(sessionStorage.getItem(KEY)!).name).toBe("B edit"));
    }
    expect(sessionStorage.getItem(KEY)).toBe(raw);
    await screen.findByText("주인을 확인할 수 없는 입력입니다");
    expect(screen.queryByPlaceholderText(NAME_PLACEHOLDER)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBe(raw);
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });
  it("주인을 모르는 초안은 편집할 수 없는 이름 대신 실제 잠금 사유를 표시한다", async () => {
    const raw = JSON.stringify({ name: "", siteId: "", aoi: [], egressChoice: "allow" });
    sessionStorage.setItem(KEY, raw);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    await screen.findByText("주인을 확인할 수 없는 입력입니다");
    expect(screen.queryByText("현장 이름을 입력하세요.")).toBeNull();
    expect(screen.getByText("이 입력의 원래 계정을 확인할 수 없어 표시하지 않습니다. 현장 목록에서 먼저 확인하세요.")).toBeTruthy();
    expect(screen.queryByText(/입력 내용은 자동 저장됩니다/)).toBeNull();
    expect(screen.getAllByText(/저장된 입력을 표시하거나 변경하지 않습니다/).length).toBeGreaterThan(0);
    expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
    expect(sessionStorage.getItem(KEY)).toBe(raw);
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });
  it("다른 계정의 초안도 편집할 수 없는 이름이 아니라 계정 복귀를 안내한다", async () => {
    const other = `v1-${"b".repeat(64)}`;
    const raw = JSON.stringify({ name: "", siteId: "", aoi: [], originFingerprint: other });
    sessionStorage.setItem(KEY, raw);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    await screen.findByText("다른 계정의 입력입니다");
    expect(screen.queryByText("현장 이름을 입력하세요.")).toBeNull();
    expect(screen.getByText("저장된 입력의 계정과 이 화면의 계정 정보가 다릅니다. 원래 계정으로 돌아오세요.")).toBeTruthy();
    expect(screen.queryByText(/입력 내용은 자동 저장됩니다/)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBe(raw);
  });
  it("새 빈 초안에서는 기존 이름 입력 안내를 유지한다", async () => {
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    await screen.findByPlaceholderText(NAME_PLACEHOLDER);
    expect(screen.getByText("현장 이름을 입력하세요.")).toBeTruthy();
    expect(screen.getByText(/입력 내용은 자동 저장됩니다/)).toBeTruthy();
  });
  it.each(["MAPPED_BOOTSTRAP", "LEGACY_SITE_ID"] as const)("%s 구 초안의 잔여 본문 단독·조합을 잠근다", async (mode) => {
    for (const fields of [
      { egressChoice: "allow" }, { egressChoice: "deny" }, { jurisdiction: "KR" },
      { aiEgressAllowed: true }, { crs: "EPSG:5186" }, { verticalDatum: "datum" },
      { transformVersion: "2.0.0" }, { transformVersion: "" }, { name: " " },
      { mapDraftId: "11111111-2222-4333-8444-555555555555" },
      { egressChoice: "allow", jurisdiction: "KR", aiEgressAllowed: true, crs: "EPSG:5186" },
    ]) {
      const raw = JSON.stringify({ name: "", siteId: "", aoi: [], ...fields });
      sessionStorage.setItem(KEY, raw);
      const view = render(<SiteRegistrationOnlyWizard mode={mode} accountFingerprint={IDENTITY} />);
      await screen.findByText("주인을 확인할 수 없는 입력입니다");
      expect(screen.queryByPlaceholderText(NAME_PLACEHOLDER)).toBeNull();
      expect(sessionStorage.getItem(KEY)).toBe(raw);
      const fresh = screen.getByRole("link", { name: "별도 탭에서 새로 시작하기" });
      expect(fresh.getAttribute("target")).toBe("_blank");
      expect(fresh.getAttribute("rel")).toContain("noopener");
      view.unmount();
    }
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });

  it("빈 구 기본값은 새 입력을 허용하지만 이전 미상 기록을 보존한다", async () => {
    const unknown = { kind: "mapped", key: "old", originFingerprint: IDENTITY, payloadDigest: "{}", name: "prior" };
    sessionStorage.setItem(KEY, JSON.stringify({ siteId: "", name: "", aoi: [], crs: "", verticalDatum: "", transformVersion: "1.0.0", egressChoice: "unset", jurisdiction: "", aiEgressAllowed: false, priorUnknowns: [unknown] }));
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    fireEvent.change(await screen.findByPlaceholderText(NAME_PLACEHOLDER), { target: { value: "new input" } });
    await waitFor(() => expect(JSON.parse(sessionStorage.getItem(KEY)!).name).toBe("new input"));
    expect(JSON.parse(sessionStorage.getItem(KEY)!).priorUnknowns).toEqual([unknown]);
  });

  it("주체 미상 본문은 A→B→A 전환 뒤에도 원문과 계정 미상을 유지한다", async () => {
    const raw = JSON.stringify({ name: "", siteId: "", aoi: [], jurisdiction: "KR", priorUnknowns: [{ unexpected: "keep" }] });
    sessionStorage.setItem(KEY, raw);
    for (const fingerprint of [IDENTITY, `v1-${"b".repeat(64)}`, IDENTITY]) {
      vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ fingerprint }), { status: 200 }));
      const view = render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={fingerprint} />);
      await screen.findByText("주인을 확인할 수 없는 입력입니다");
      expect(screen.queryByPlaceholderText(NAME_PLACEHOLDER)).toBeNull();
      expect(sessionStorage.getItem(KEY)).toBe(raw);
      view.unmount();
    }
  });
  it.each(["", '{"origin":"unknown",', '"unrecognized original"'])(
    "읽을 수 없는 저장값을 덮지 않고 등록 대신 복구 안내를 표시한다",
    async (raw) => {
      sessionStorage.setItem(KEY, raw);
      render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);

      await waitFor(() => expect(screen.getByText(/저장된 현장 초안을 읽을 수 없습니다/)).toBeTruthy());
      expect(screen.queryByPlaceholderText(NAME_PLACEHOLDER)).toBeNull();
      const next = screen.queryByRole("button", { name: "다음" }) as HTMLButtonElement | null;
      expect(next === null || next.disabled).toBe(true);
      expect(sessionStorage.getItem(KEY)).toBe(raw);
      expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);

      cleanup();
      render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
      await screen.findByText(/저장된 현장 초안을 읽을 수 없습니다/);
      expect(sessionStorage.getItem(KEY)).toBe(raw);
    },
  );

  it("이름과 지도 없이 식별자만 남은 주체 미상 초안도 현재 계정으로 귀속하지 않는다", async () => {
    const legacy = {
      siteId: "private-legacy-id",
      bootstrapRequestId: "11111111-2222-4333-8444-555555555555",
      name: "",
      aoi: [],
      crs: "EPSG:5186",
    };
    sessionStorage.setItem(KEY, JSON.stringify(legacy));
    render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={IDENTITY} />);

    await screen.findByText("주인을 확인할 수 없는 입력입니다");
    expect(screen.queryByDisplayValue("private-legacy-id")).toBeNull();
    const stored = JSON.parse(sessionStorage.getItem(KEY)!) as typeof legacy & { originFingerprint?: string };
    expect(stored.siteId).toBe(legacy.siteId);
    expect(stored.bootstrapRequestId).toBe(legacy.bootstrapRequestId);
    expect(stored.originFingerprint).toBeUndefined();
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });

  it("원래 지문이 잘못된 초안은 원문 지문과 요청 키까지 바꾸지 않는다", async () => {
    const raw = JSON.stringify({
      name: "Synthetic legacy site",
      aoi: [],
      originFingerprint: "malformed-original-identity",
      bootstrapRequestId: "11111111-2222-4333-8444-555555555555",
    });
    sessionStorage.setItem(KEY, raw);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    await screen.findByText("주인을 확인할 수 없는 입력입니다");
    expect(screen.queryByDisplayValue("Synthetic legacy site")).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBe(raw);
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    await screen.findByText("주인을 확인할 수 없는 입력입니다");
    expect(sessionStorage.getItem(KEY)).toBe(raw);
  });

  it("형식이 다른 기존 요청 키는 유효한 신원이 있어도 버리지 않고 저장 원문을 잠근다", async () => {
    const raw = JSON.stringify({ name: "요청 키 원문", aoi: [], originFingerprint: IDENTITY, bootstrapRequestId: "original-request-key-not-a-uuid" });
    sessionStorage.setItem(KEY, raw);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    expect(await screen.findByText(/저장된 현장 초안을 읽을 수 없습니다/)).toBeTruthy();
    expect(screen.queryByPlaceholderText(NAME_PLACEHOLDER)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBe(raw);
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });

  it("서버 렌더 뒤 계정이 바뀌었을 수 있으면 최초 실시간 확인 전부터 초안을 숨긴다", async () => {
    const original = {
      name: "Synthetic private site",
      siteId: "",
      aoi: [],
      originFingerprint: IDENTITY,
    };
    sessionStorage.setItem(KEY, JSON.stringify(original));
    let reply: (response: Response) => void = () => {};
    const pending = new Promise<Response>((resolve) => { reply = resolve; });
    vi.mocked(fetch).mockImplementation(() => pending);

    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    expect(screen.queryByDisplayValue(original.name)).toBeNull();
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/account-identity", { cache: "no-store" }));
    await act(async () => reply(new Response(JSON.stringify({ fingerprint: `v1-${"b".repeat(64)}` }), { status: 200 })));
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
    expect(screen.queryByDisplayValue(original.name)).toBeNull();
    expect(JSON.parse(sessionStorage.getItem(KEY)!).originFingerprint).toBe(IDENTITY);
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });
});

describe("실시간 계정과 저장 상태", () => {
  it("신규 사용자가 live 확인 후 편집하면 저장하고 재진입에서 복원한다", async () => {
    const { unmount } = render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    const input = await screen.findByPlaceholderText(NAME_PLACEHOLDER);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(input, { target: { value: "synthetic new site" } });
    await waitFor(() => expect(JSON.parse(sessionStorage.getItem(KEY)!).name).toBe("synthetic new site"));
    unmount();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    expect(await screen.findByDisplayValue("synthetic new site")).toBeTruthy();
  });

  it("쓰기 실패를 안내하고 저장 성공이라고 말하지 않는다", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    const input = await screen.findByPlaceholderText(NAME_PLACEHOLDER);
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(input, { target: { value: "unsaved" } });
    expect((await screen.findAllByText(/임시저장 실패/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/입력 내용은 자동 저장됩니다/)).toBeNull();
  });

  it("실시간 확인 실패에는 기존 데이터와 입력을 숨긴다", async () => {
    const raw = JSON.stringify({ name: "secret", aoi: [], originFingerprint: IDENTITY });
    sessionStorage.setItem(KEY, raw);
    vi.mocked(fetch).mockRejectedValue(new Error("offline"));
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
    expect(await screen.findByText(/현재 계정을 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByDisplayValue("secret")).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBe(raw);
  });
});

it("실제 편집 및 재진입 뒤에도 손상된 이전 요청을 격리 보존한다", async () => {
  const broken = { key: "synthetic damaged entry", originFingerprint: null, future: [1, 2] };
  sessionStorage.setItem(KEY, JSON.stringify({ name: "before", aoi: [], originFingerprint: IDENTITY, priorUnknowns: [broken] }));
  const { unmount } = render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
  const input = await screen.findByDisplayValue("before");
  const { fireEvent } = await import("@testing-library/react");
  fireEvent.change(input, { target: { value: "after" } });
  await waitFor(() => expect(JSON.parse(sessionStorage.getItem(KEY)!).quarantinedUnknowns).toEqual([broken]));
  unmount();
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
  await screen.findByDisplayValue("after");
  expect(JSON.parse(sessionStorage.getItem(KEY)!).quarantinedUnknowns).toEqual([broken]);
});

it("StrictMode 최초 확인이 완료되기 전 저장된 초안을 공개하거나 다시 쓰지 않는다", async () => {
  const { StrictMode } = await import("react");
  const raw = '{ "name": "strict private", "aoi": [], "originFingerprint": "' + IDENTITY + '", "future": "원문" }';
  sessionStorage.setItem(KEY, raw);
  let resolveIdentity: (response: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => { resolveIdentity = resolve; });
  vi.mocked(fetch).mockImplementation(async () => (await pending).clone());
  render(<StrictMode><SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} /></StrictMode>);
  expect(screen.queryByDisplayValue("strict private")).toBeNull();
  expect(sessionStorage.getItem(KEY)).toBe(raw);
  await act(async () => resolveIdentity(new Response(JSON.stringify({ fingerprint: IDENTITY }), { status: 200 })));
  expect(await screen.findByDisplayValue("strict private")).toBeTruthy();
  expect(sessionStorage.getItem(KEY)).toBe(raw);
});

it("늦게 도착한 최초 계정 확인이 최신 포커스 확인을 덮지 않는다", async () => {
  const OTHER = `v1-${"b".repeat(64)}`;
  const raw = JSON.stringify({ name: "race private", aoi: [], originFingerprint: IDENTITY });
  sessionStorage.setItem(KEY, raw);
  let resolveInitial: (response: Response) => void = () => {};
  const pending = new Promise<Response>((resolve) => { resolveInitial = resolve; });
  vi.mocked(fetch).mockImplementationOnce(() => pending).mockResolvedValueOnce(new Response(JSON.stringify({ fingerprint: OTHER }), { status: 200 }));
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
  await act(async () => resolveInitial(new Response(JSON.stringify({ fingerprint: IDENTITY }), { status: 200 })));
  expect(screen.getByText("다른 계정의 입력입니다")).toBeTruthy();
  expect(screen.queryByDisplayValue("race private")).toBeNull();
  expect(sessionStorage.getItem(KEY)).toBe(raw);
});

it("주체 미상 플래그는 유효 지문이 함께 있어도 해제하거나 원문을 덮지 않는다", async () => {
  const raw = JSON.stringify({ name: "주체 불확실한 초안", aoi: [], originFingerprint: IDENTITY, originUnknown: true });
  sessionStorage.setItem(KEY, raw);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
  expect(await screen.findByText("주인을 확인할 수 없는 입력입니다")).toBeTruthy();
  expect(screen.queryByDisplayValue("주체 불확실한 초안")).toBeNull();
  expect(sessionStorage.getItem(KEY)).toBe(raw);
  expect(vi.mocked(fetch).mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
});

it.each(["true", null, 1, {}])("주체 미상 플래그의 잘못된 타입 %j는 읽기 실패로 잠그고 원문을 보존한다", async (originUnknown) => {
  const raw = JSON.stringify({ name: "private", aoi: [], originFingerprint: IDENTITY, originUnknown });
  sessionStorage.setItem(KEY, raw);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={IDENTITY} />);
  expect(await screen.findByText(/저장된 현장 초안을 읽을 수 없습니다/)).toBeTruthy();
  expect(screen.queryByDisplayValue("private")).toBeNull();
  expect(sessionStorage.getItem(KEY)).toBe(raw);
});
