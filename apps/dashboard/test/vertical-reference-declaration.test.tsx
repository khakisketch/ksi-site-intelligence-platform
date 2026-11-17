/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import type { VerticalDeclarationRecord, VerticalDeclarationState } from "@/lib/core-api/vertical-reference-types";
import { VerticalReferenceDeclaration } from "@/app/sites/[siteId]/materials/VerticalReferenceDeclaration";

const ASSET = `ksa-v1-${"a".repeat(64)}`;
const DIGEST = `sha256:${"b".repeat(64)}`;
const URL_BASE = `/api/sites/site-1/work-areas/area-1/spatial-assets/${ASSET}/vertical-reference`;

const record = (sequence: number, overrides: Partial<VerticalDeclarationRecord> = {}): VerticalDeclarationRecord => ({
  declarationId: `vrd-${String(sequence).repeat(32)}`, siteId: "site-1", workAreaId: "area-1", assetRef: ASSET, sequence, status: "ACTIVE",
  datum: "orthometric_kngeoid2018", unit: "metre", basis: "Terra에서 내보냄", declaredBy: "operator-1", declaredAt: "2026-11-17T01:00:00Z",
  declarationDigest: DIGEST, ...overrides,
});
const none: VerticalDeclarationState = { assetRef: ASSET, observed: false, current: null, history: [] };
const declared: VerticalDeclarationState = { assetRef: ASSET, observed: false, current: record(1), history: [record(1)] };
const afterWithdrawal: VerticalDeclarationState = { assetRef: ASSET, observed: false, current: null, history: [record(1), record(2, { status: "WITHDRAWN", datum: null, basis: null })] };

const fetchMock = vi.fn();
function show(state: VerticalDeclarationState | null, canWrite = true) {
  return render(<VerticalReferenceDeclaration siteId="site-1" workAreaId="area-1" assetRef={ASSET} state={state} canWrite={canWrite} />);
}
const reply = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  router.refresh.mockReset();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function fillForm(basis = "Terra 내보내기 설정에서 정표고를 선택함") {
  fireEvent.click(screen.getByRole("radio", { name: /정표고 \(KNGeoid2018\)/ }));
  fireEvent.change(screen.getByLabelText(/근거/), { target: { value: basis } });
  fireEvent.click(screen.getByRole("checkbox", { name: /높이 단위가 미터임을 확인/ }));
}
const submit = () => screen.getByRole("button", { name: "선언하기" }) as HTMLButtonElement;

describe("수직 기준이 없는 DSM", () => {
  it("선언이 없으면 이유와 범위를 말하고, 기준·근거·단위 확인이 모두 있어야 선언할 수 있다", () => {
    show(none);
    const section = screen.getByRole("region", { name: "수직 기준 선언" });
    expect(section.textContent).toContain("수직 기준(높이 기준)이 없어 높이·단면을 읽을 수 없습니다");
    expect(section.textContent).toContain("체적과 두 시점 비교에는 쓰이지 않습니다");
    expect(submit().disabled).toBe(true);
    // 근거와 단위 확인만 있고 기준을 고르지 않은 경우
    fireEvent.change(screen.getByLabelText(/근거/), { target: { value: "근거" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /높이 단위가 미터임을 확인/ }));
    expect(submit().disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: /높이 단위가 미터임을 확인/ }));
    fireEvent.change(screen.getByLabelText(/근거/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("radio", { name: /정표고 \(KNGeoid2018\)/ }));
    expect(submit().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/근거/), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("checkbox", { name: /높이 단위가 미터임을 확인/ }));
    expect(submit().disabled).toBe(true); // 공백뿐인 근거
    fireEvent.change(screen.getByLabelText(/근거/), { target: { value: "근거" } });
    expect(submit().disabled).toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: /높이 단위가 미터임을 확인/ }));
    expect(submit().disabled).toBe(true); // 단위 확인을 거둠
  });

  it("틀릴 수 있음을 숨기지 않는다", () => {
    show(none);
    expect(screen.getByRole("region", { name: "수직 기준 선언" }).textContent).toContain("KSI가 확인하지 않습니다");
  });

  it("선언을 한 번만 보내고 성공하면 화면을 새로 읽는다", async () => {
    fetchMock.mockResolvedValue(reply(201, { declaration: record(1) }));
    show(none);
    await fillForm();
    fireEvent.click(submit());
    await waitFor(() => expect(router.refresh).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${URL_BASE}/declarations`);
    expect(JSON.parse(init.body as string)).toEqual({ datum: "orthometric_kngeoid2018", unit: "metre", basis: "Terra 내보내기 설정에서 정표고를 선택함", expectedSequence: 0 });
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toMatch(/^console-/);
  });

  it("서버가 거부하면 이유를 말하고 화면을 새로 읽지 않는다", async () => {
    fetchMock.mockResolvedValue(reply(409, { code: "OBSERVED_REFERENCE_PRESENT" }));
    show(none);
    await fillForm();
    fireEvent.click(submit());
    expect((await screen.findByRole("alert")).textContent).toContain("이미 수직 기준을 담고 있어 선언이 필요 없습니다");
    expect(router.refresh).not.toHaveBeenCalled();
  });

  it("응답을 모르는 실패는 같은 키로 다시 시도하고, 거부를 받으면 새 키를 쓴다", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network"));
    fetchMock.mockResolvedValueOnce(reply(409, { code: "SEQUENCE_CONFLICT" }));
    fetchMock.mockResolvedValueOnce(reply(201, { declaration: record(1) }));
    show(none);
    await fillForm();
    fireEvent.click(submit());
    expect((await screen.findByRole("alert")).textContent).toContain("응답을 확인하지 못했습니다");
    fireEvent.click(submit());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const keys = () => fetchMock.mock.calls.map(([, init]) => (init as RequestInit & { headers: Record<string, string> }).headers["Idempotency-Key"]);
    expect(keys()[1]).toBe(keys()[0]); // 응답을 모르니 같은 요청이다
    await screen.findByText(/다른 사람이 먼저 선언을 바꿨습니다/);
    fireEvent.click(submit());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(keys()[2]).not.toBe(keys()[1]); // 서버가 답했으니 새 요청이다
  });

  it("두 번 눌러도 요청은 하나다", async () => {
    let release: (value: unknown) => void = () => undefined;
    fetchMock.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    show(none);
    await fillForm();
    const button = submit();
    fireEvent.click(button);
    fireEvent.click(button);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    release(reply(201, { declaration: record(1) }));
    await waitFor(() => expect(router.refresh).toHaveBeenCalled());
  });

  it("버튼을 거치지 않고 양식을 두 번 제출해도 요청은 하나다", async () => {
    let release: (value: unknown) => void = () => undefined;
    fetchMock.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    show(none);
    await fillForm();
    const form = submit().closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    release(reply(201, { declaration: record(1) }));
    await waitFor(() => expect(router.refresh).toHaveBeenCalled());
  });

  it("조건이 모자란 양식은 제출해도 보내지 않는다", () => {
    show(none);
    fireEvent.submit(submit().closest("form")!);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("철회된 이력이 있으면 그 사실을 알리고 새 선언의 sequence는 이력 길이다", async () => {
    fetchMock.mockResolvedValue(reply(201, { declaration: record(3) }));
    show(afterWithdrawal);
    expect(screen.getByRole("region", { name: "수직 기준 선언" }).textContent).toContain("이전 선언은 철회되었습니다");
    await fillForm();
    fireEvent.click(submit());
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string).expectedSequence).toBe(2);
  });
});

describe("선언된 DSM", () => {
  it("사용자 선언임과 검증되지 않았음을 함께 보인다", () => {
    show(declared);
    const text = screen.getByRole("region", { name: "수직 기준 선언" }).textContent ?? "";
    expect(text).toContain("사용자 선언 · 정표고(KNGeoid2018)");
    expect(text).toContain("높이 단위 미터");
    expect(text).toContain("근거: Terra에서 내보냄");
    expect(text).toContain("operator-1");
    expect(text).toContain("파일에서 확인되지 않은 값이며 KSI는 검증하지 않습니다");
    expect(text).not.toMatch(/정확|검증됨|확인됨/);
  });

  it("정정은 현재 선언을 채워 열고 본 sequence를 싣는다", async () => {
    fetchMock.mockResolvedValue(reply(201, { declaration: record(2) }));
    show(declared);
    fireEvent.click(screen.getByRole("button", { name: "정정하기" }));
    expect((screen.getByRole("radio", { name: /정표고 \(KNGeoid2018\)/ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText(/근거/) as HTMLInputElement).value).toBe("Terra에서 내보냄");
    // 단위는 정정할 때도 다시 확인한다.
    expect((screen.getByRole("button", { name: "정정을 저장" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /^타원체고$|타원체고\s*GNSS/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /높이 단위가 미터임을 확인/ }));
    fireEvent.click(screen.getByRole("button", { name: "정정을 저장" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toMatchObject({ datum: "ellipsoidal", expectedSequence: 1 });
  });

  it("철회는 확인을 한 번 더 거치고, 결과가 닫힌다는 것을 알린다", async () => {
    fetchMock.mockResolvedValue(reply(201, { declaration: record(2, { status: "WITHDRAWN", datum: null, basis: null }) }));
    show(declared);
    fireEvent.click(screen.getByRole("button", { name: "철회하기" }));
    expect(fetchMock).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog", { name: "선언 철회 확인" });
    expect(dialog.textContent).toContain("단면 결과도 더 이상 열리지 않고");
    fireEvent.click(within(dialog).getByRole("button", { name: "철회합니다" }));
    await waitFor(() => expect(router.refresh).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${URL_BASE}/withdrawals`);
    expect(JSON.parse(init.body as string)).toEqual({ expectedSequence: 1 });
  });

  it("철회 확인을 취소하면 아무것도 보내지 않는다", () => {
    show(declared);
    fireEvent.click(screen.getByRole("button", { name: "철회하기" }));
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("권한과 읽기 실패", () => {
  it("쓰기 권한이 없으면 선언 내용은 읽기만 하고 조작을 보이지 않는다", () => {
    show(declared, false);
    expect(screen.queryByRole("button", { name: "정정하기" })).toBeNull();
    expect(screen.queryByRole("button", { name: "철회하기" })).toBeNull();
    expect(screen.getByRole("region", { name: "수직 기준 선언" }).textContent).toContain("작업 등록 권한이 있는 계정이 할 수 있습니다");
    cleanup();
    show(none, false);
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("button", { name: "선언하기" })).toBeNull();
  });

  it("선언 상태를 읽지 못하면 선언이 없다고 말하지 않고 조작도 열지 않는다", () => {
    show(null);
    const text = screen.getByRole("region", { name: "수직 기준 선언" }).textContent ?? "";
    expect(text).toContain("선언 상태를 불러오지 못했습니다");
    expect(text).toContain("선언이 없다는 뜻이 아닙니다");
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
