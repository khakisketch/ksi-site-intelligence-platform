/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MaskedAnalysisPanel } from "@/app/sites/[siteId]/analysis/MaskedAnalysisPanel";

const fixture = JSON.parse(
  readFileSync("test/masked-wire-fixture.json", "utf-8"),
) as Record<string, unknown>;

const baseProps = {
  siteId: "site-1",
  workAreaId: "area-1",
  workAreaName: "구역 A",
  canRequest: true,
  maskBudgetBytes: 1024 * 1024,
};

const digest = fixture.sourceCalculationIdentityDigest as string;

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MaskedAnalysisPanel", () => {
  it("원본이 없으면 마스크 입력 연결 전으로만 둔다", () => {
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        sourceCalculationIdentityDigest={null}
        initialChild={null}
        initialCalculation={null}
      />,
    );
    expect(screen.getByText(/마스크 입력 연결 전/)).toBeTruthy();
    expect(screen.queryByLabelText(/마스크 TIFF 선택/)).toBeNull();
  });

  it("원본 맥락이 오기 전에는 선언을 막고 명시적 조회만 둔다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(fixture.sourceContext)));
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        sourceCalculationIdentityDigest={digest}
        initialChild={null}
        initialCalculation={null}
      />,
    );
    expect(screen.getAllByText(/원본 맥락 연결 전/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "마스크 설정 불러오기" }));
    await waitFor(() => expect(screen.getByText(/원본 맥락 확인됨/)).toBeTruthy());
    expect(screen.getByText(/임시 허용 — 품질 인증이 아닙니다/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "마스크 입력 선언" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("승인되지 않은 원본은 사유 코드와 함께 둔다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ message: "승인되지 않은 원본입니다.", code: "SOURCE_NOT_ADMITTED" }, 409)));
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        sourceCalculationIdentityDigest={digest}
        initialChild={null}
        initialCalculation={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "마스크 설정 불러오기" }));
    await waitFor(() => expect(screen.getAllByText("승인되지 않은 원본입니다.").length).toBeGreaterThan(0));
    expect(screen.getByText("SOURCE_NOT_ADMITTED")).toBeTruthy();
  });

  it("예산이 없으면 파일 선택을 막는다", () => {
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        maskBudgetBytes={null}
        sourceCalculationIdentityDigest={digest}
        initialChild={null}
        initialCalculation={null}
      />,
    );
    expect((screen.getByLabelText(/마스크 TIFF 선택/) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/업로드 예산이 설정되지 않아/)).toBeTruthy();
  });

  it("검사 완료 자식은 V3 요청 가능 상태로 둔다", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      const url = String(input);
      if (url.includes("/inspection-status")) return jsonResponse(fixture.inspectionCompleted);
      return jsonResponse(fixture.childViewReady);
    }));
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sourceCalculationIdentityDigest={digest}
          initialChild={fixture.childViewReady as never}
          initialCalculation={null}
        />,
      );
      expect(screen.getByText(/검사 상태를 새로고침으로 확인하세요/)).toBeTruthy();
      expect((screen.getByRole("button", { name: "V3 계산 요청" }) as HTMLButtonElement).disabled).toBe(true);
      fireEvent.click(screen.getByRole("button", { name: "검사 상태 새로고침" }));
      await waitFor(() => expect(screen.getAllByText(/검사 완료\(봉인됨\)/).length).toBeGreaterThan(0));
      expect((screen.getByRole("button", { name: "V3 계산 요청" }) as HTMLButtonElement).disabled).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("AVAILABLE 화면에서 알 수 없는 제외 영역을 0으로 채우지 않는다", () => {
    const onDeltaHandoff = vi.fn();
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        sourceCalculationIdentityDigest={digest}
        initialChild={fixture.childViewReady as never}
        initialCalculation={fixture.detailViewUnknownImpact as never}
        onDeltaHandoff={onDeltaHandoff}
      />,
    );
    expect(screen.getByText(/제외 영역의 원래 수치는 확인할 수 없음/)).toBeTruthy();
    expect(screen.getByText(/임시 허용이며 품질 인증이 아닙니다/)).toBeTruthy();
    expect(screen.getByText(/독립 마스크 계산 결과/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "내보내기로 인계" }));
    expect(onDeltaHandoff).toHaveBeenCalledTimes(1);
    const unknownDetail = fixture.detailViewUnknownImpact as {
      admission: { sourceCalculationIdentityDigest: string };
      report: { numericResultIdentityDigest: string; numericResult: { coverage: { coverageWitnessDigest: string } } };
    };
    expect(onDeltaHandoff.mock.calls[0]?.[0]).toEqual({
      sourceCalculationIdentityDigest: unknownDetail.admission.sourceCalculationIdentityDigest,
      sourceNumericResultIdentityDigest: unknownDetail.report.numericResultIdentityDigest,
      sourceCoverageWitnessDigest: unknownDetail.report.numericResult.coverage.coverageWitnessDigest,
      maskChildId: "mask-child-1",
    });
  });

  it("사용자 새로고침으로 AVAILABLE을 확인하면 onResult를 방출한다", async () => {
    const onResult = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(fixture.detailViewAvailable)));
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        sourceCalculationIdentityDigest={digest}
        initialChild={fixture.childViewReady as never}
        initialCalculation={fixture.detailViewPending as never}
        onResult={onResult}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "V3 화면 새로고침" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledTimes(1));
    expect(onResult.mock.calls[0]?.[0]).toEqual(fixture.detailViewAvailable);
  });

  it("AVAILABLE 다음 재평가 화면도 onResult로 알린다(부모가 낡은 출처를 무효화)", async () => {
    const onResult = vi.fn();
    const reassessed = {
      ...(fixture.detailViewAvailable as Record<string, unknown>),
      disposition: "REASSESSMENT_REQUIRED",
      report: null,
    };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(reassessed)));
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        sourceCalculationIdentityDigest={digest}
        initialChild={fixture.childViewReady as never}
        initialCalculation={fixture.detailViewAvailable as never}
        onResult={onResult}
      />,
    );
    expect(screen.getByText(/독립 마스크 계산 결과/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "V3 화면 새로고침" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledTimes(1));
    expect(onResult.mock.calls[0]?.[0]).toEqual(reassessed);
    expect(screen.queryByText(/독립 마스크 계산 결과/)).toBeNull();
    expect(screen.getByText(/재평가가 필요합니다/)).toBeTruthy();
  });

  it("REJECTED 검사는 사유와 함께 두고 생성을 막는다", async () => {
    const onInvalidated = vi.fn();
    const onResult = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      const url = String(input);
      if (url.includes("/inspection-status")) return jsonResponse({ ...(fixture.inspectionRejected as object), maskChildId: "mask-child-1" });
      return jsonResponse(fixture.childViewPending);
    }));
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sourceCalculationIdentityDigest={digest}
          initialChild={fixture.childViewPending as never}
          initialCalculation={null}
          onInvalidated={onInvalidated}
          onResult={onResult}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "검사 상태 새로고침" }));
      await waitFor(() => expect(screen.getAllByText(/NoData가 있는 마스크는 사용할 수 없습니다/).length).toBeGreaterThan(0));
      expect(onInvalidated).toHaveBeenCalled();
      expect(onResult).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: "V3 계산 요청" })).toBeNull();
      expect(screen.queryByRole("button", { name: "마스크 업로드" })).toBeNull();
      expect((screen.getByLabelText(/마스크 TIFF 선택/) as HTMLInputElement).disabled).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("복원된 REJECTED는 가짜 완료를 만들지 않는다", async () => {
    const onInvalidated = vi.fn();
    const onResult = vi.fn();
    const recordScope = {
      organizationId: "org-1",
      principalId: "op-1",
      siteId: "site-1",
      workAreaId: "area-1",
      sourceCalculationIdentityDigest: digest,
    };
    const recordKey = [
      "ksi.masked.continuity.v1:",
      "org-1",
      "op-1",
      "site-1",
      "area-1",
      encodeURIComponent(digest),
    ].join(":");
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      const url = String(input);
      if (url.includes("/inspection-status")) return jsonResponse({ ...(fixture.inspectionRejected as object), maskChildId: "mask-child-1" });
      return jsonResponse(fixture.childViewPending);
    }));
    window.sessionStorage.setItem(recordKey, JSON.stringify({
      version: 1,
      scope: recordScope,
      maskChildId: "mask-child-1",
      requestId: null,
    }));
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sessionScope={{ organizationId: "org-1", principalId: "op-1" }}
          sourceCalculationIdentityDigest={digest}
          initialChild={null}
          initialCalculation={null}
          onInvalidated={onInvalidated}
          onResult={onResult}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "이전 마스크 작업 불러오기" }));
      await waitFor(() => expect(screen.getAllByText(/NoData 없이 새 파일을 등록하세요/).length).toBeGreaterThan(0));
      expect(onInvalidated).toHaveBeenCalled();
      expect(onResult).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: "V3 계산 요청" })).toBeNull();
      expect(screen.queryByText(/독립 마스크 계산 결과/)).toBeNull();
    } finally {
      window.sessionStorage.clear();
    }
  });

  it("PENDING 화면은 수치 없이 승인 대기만 둔다", () => {
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        sourceCalculationIdentityDigest={digest}
        initialChild={fixture.childViewReady as never}
        initialCalculation={fixture.detailViewPending as never}
      />,
    );
    expect(screen.getByText(/승인이 대기 중입니다/)).toBeTruthy();
    expect(screen.queryByText(/독립 마스크 계산 결과/)).toBeNull();
  });

  it("실패 응답의 코드는 접힌 상세로만 둔다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ message: "펜스가 만료되었습니다.", code: "MASKED_INPUT_FENCE_REJECTED" }, 409)));
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        sourceCalculationIdentityDigest={digest}
        initialChild={fixture.childViewReady as never}
        initialCalculation={fixture.detailViewPending as never}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "V3 화면 새로고침" }));
    await waitFor(() => expect(screen.getAllByText("펜스가 만료되었습니다.").length).toBeGreaterThan(0));
    expect(screen.getByText("MASKED_INPUT_FENCE_REJECTED")).toBeTruthy();
  });

  it("쓰기 권한이 없으면 선언 동작을 안내로 둔다", () => {
    render(
      <MaskedAnalysisPanel
        {...baseProps}
        canRequest={false}
        sourceCalculationIdentityDigest={digest}
        initialChild={null}
        initialCalculation={null}
      />,
    );
    expect(screen.getByRole("button", { name: "마스크 입력 선언" })).toBeTruthy();
  });

describe("작업 연속성", () => {
  const sessionScope = { organizationId: "org-1", principalId: "op-1" };
  const recordScope = {
    organizationId: "org-1",
    principalId: "op-1",
    siteId: "site-1",
    workAreaId: "area-1",
    sourceCalculationIdentityDigest: digest,
  };
  const record = {
    version: 1,
    scope: recordScope,
    maskChildId: "mask-child-1",
    requestId: "req-v3-1",
  };
  const key = [
    "ksi.masked.continuity.v1:",
    "org-1",
    "op-1",
    "site-1",
    "area-1",
    encodeURIComponent(digest),
  ].join(":");

  const seed = (value: unknown) => {
    window.sessionStorage.setItem(key, typeof value === "string" ? value : JSON.stringify(value));
  };

  it("마운트 시 자동 요청 없이 복원을 내놓는다", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    seed(record);
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sessionScope={sessionScope}
          sourceCalculationIdentityDigest={digest}
          initialChild={null}
          initialCalculation={null}
        />,
      );
      expect(screen.getByRole("button", { name: "이전 마스크 작업 불러오기" })).toBeTruthy();
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      window.sessionStorage.clear();
    }
  });

  it("명시적 읽기 뒤 AVAILABLE 화면을 부모에 알리고 버튼을 닫는다", async () => {
    const onResult = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
      const url = String(input);
      if (url.includes("/masked-analyses/")) return jsonResponse(fixture.detailViewAvailable);
      if (url.includes("/inspection-status")) return jsonResponse(fixture.inspectionCompleted);
      return jsonResponse(fixture.childViewReady);
    }));
    seed(record);
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sessionScope={sessionScope}
          sourceCalculationIdentityDigest={digest}
          initialChild={null}
          initialCalculation={null}
          onResult={onResult}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "이전 마스크 작업 불러오기" }));
      await waitFor(() => expect(onResult).toHaveBeenCalledTimes(1));
      expect(onResult.mock.calls[0]?.[0]).toEqual(fixture.detailViewAvailable);
      expect(screen.getByText(/독립 마스크 계산 결과/)).toBeTruthy();
      expect(screen.queryByRole("button", { name: "이전 마스크 작업 불러오기" })).toBeNull();
    } finally {
      window.sessionStorage.clear();
    }
  });

  it("다른 사용자에게는 복원을 내놓지 않는다", () => {
    seed(record);
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sessionScope={{ organizationId: "org-1", principalId: "op-2" }}
          sourceCalculationIdentityDigest={digest}
          initialChild={null}
          initialCalculation={null}
        />,
      );
      expect(screen.queryByRole("button", { name: "이전 마스크 작업 불러오기" })).toBeNull();
    } finally {
      window.sessionStorage.clear();
    }
  });

  it("세션 범위가 없으면 복원을 내놓지 않는다", () => {
    seed(record);
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sourceCalculationIdentityDigest={digest}
          initialChild={null}
          initialCalculation={null}
        />,
      );
      expect(screen.queryByRole("button", { name: "이전 마스크 작업 불러오기" })).toBeNull();
    } finally {
      window.sessionStorage.clear();
    }
  });

  it("깨진 기록은 내놓지 않는다", () => {
    seed("{broken");
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sessionScope={sessionScope}
          sourceCalculationIdentityDigest={digest}
          initialChild={null}
          initialCalculation={null}
        />,
      );
      expect(screen.queryByRole("button", { name: "이전 마스크 작업 불러오기" })).toBeNull();
      expect(window.sessionStorage.getItem(key)).toBeNull();
    } finally {
      window.sessionStorage.clear();
    }
  });

  it("403이면 기록을 지우고 onResult 없이 솔직히 둔다", async () => {
    const onResult = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ message: "접근할 수 없습니다.", code: "MASK_SCOPE_DENIED" }, 403)));
    seed(record);
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sessionScope={sessionScope}
          sourceCalculationIdentityDigest={digest}
          initialChild={null}
          initialCalculation={null}
          onResult={onResult}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "이전 마스크 작업 불러오기" }));
      await waitFor(() => expect(screen.getAllByText(/기록을 지웠습니다/).length).toBeGreaterThan(0));
      expect(onResult).not.toHaveBeenCalled();
      expect(window.sessionStorage.getItem(key)).toBeNull();
    } finally {
      window.sessionStorage.clear();
    }
  });
});

describe("멱등 재시도", () => {
  const session = { organizationId: "org-1", principalId: "op-1" };
  const recordKey = [
    "ksi.masked.continuity.v1:",
    "org-1",
    "op-1",
    "site-1",
    "area-1",
    encodeURIComponent(digest),
  ].join(":");

  const fileWithBytes = (bytes: number[], name: string) => {
    const file = new File([new Uint8Array(bytes)], name, { type: "image/tiff" });
    (file as unknown as { arrayBuffer: () => Promise<ArrayBuffer> }).arrayBuffer = async () =>
      new Uint8Array(bytes).buffer as ArrayBuffer;
    return file;
  };
  const fileA = () => fileWithBytes([0xff, 0x00], "a.tif");
  const fileB = () => fileWithBytes([0x00, 0xff, 0x01], "b.tif");

  async function waitIdle() {
    await waitFor(() => expect((screen.getByLabelText(/마스크 TIFF 선택/) as HTMLInputElement).disabled).toBe(false));
  }

  async function setupDeclared() {
    await waitIdle();
    fireEvent.click(screen.getByRole("button", { name: "마스크 설정 불러오기" }));
    await waitFor(() => expect(screen.getByText(/원본 맥락 확인됨/)).toBeTruthy());
    await waitIdle();
  }

  async function declareWithFile(file: File) {
    await waitIdle();
    const input = screen.getByLabelText(/마스크 TIFF 선택/) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    await waitIdle();
    fireEvent.click(screen.getByRole("button", { name: "파일 확인값 계산" }));
    await waitFor(() => expect(screen.getAllByText(/선언 준비됨/).length).toBeGreaterThan(0));
    await waitFor(() => expect((screen.getByRole("button", { name: "마스크 입력 선언" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "마스크 입력 선언" }));
  }

  it("생성 POST 수락 뒤 GET 실패해도 캐시는 남고 재시도는 같은 본문이다", async () => {
    const onResult = vi.fn();
    const posted: unknown[] = [];
    let getCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input);
      if (url.includes("/inspection-status")) return jsonResponse(fixture.inspectionCompleted);
      if (url.includes("/masked-analyses") && init?.method === "POST") {
        posted.push(JSON.parse(init.body as string));
        return jsonResponse(fixture.createdView, 202);
      }
      if (url.includes("/masked-analyses/")) {
        getCalls += 1;
        if (getCalls === 1) return jsonResponse({ message: "일시 오류" }, 500);
        return jsonResponse(fixture.detailViewAvailable);
      }
      return jsonResponse(fixture.childViewReady);
    }));
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sessionScope={session}
          sourceCalculationIdentityDigest={digest}
          initialChild={fixture.childViewReady as never}
          initialCalculation={null}
          onResult={onResult}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "검사 상태 새로고침" }));
      await waitFor(() => expect(screen.getAllByText(/검사 완료\(봉인됨\)/).length).toBeGreaterThan(0));
      fireEvent.click(screen.getByRole("button", { name: "V3 계산 요청" }));
      await waitFor(() => expect(screen.getAllByText("일시 오류").length).toBeGreaterThan(0));
      // GET이 실패해도 수락된 요청 id는 이미 기억된다.
      const cached = JSON.parse(window.sessionStorage.getItem(recordKey) as string);
      expect(cached.requestId).toBe("req-v3-1");
      expect(cached.maskChildId).toBe("mask-child-1");
      fireEvent.click(screen.getByRole("button", { name: "V3 계산 요청" }));
      await waitFor(() => expect(onResult).toHaveBeenCalledTimes(1));
      expect(posted.length).toBe(2);
      expect(posted[0]).toEqual(posted[1]);
    } finally {
      window.sessionStorage.clear();
      vi.unstubAllGlobals();
    }
  });

  it("생성 POST 타임아웃 뒤 재시도는 같은 본문이다", async () => {
    const posted: unknown[] = [];
    let postCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input);
      if (url.includes("/inspection-status")) return jsonResponse(fixture.inspectionCompleted);
      if (url.includes("/masked-analyses") && init?.method === "POST") {
        postCalls += 1;
        posted.push(JSON.parse(init.body as string));
        if (postCalls === 1) return jsonResponse({ message: "마스크 서버의 응답이 지연됩니다." }, 503);
        return jsonResponse(fixture.createdView, 202);
      }
      if (url.includes("/masked-analyses/")) return jsonResponse(fixture.detailViewAvailable);
      return jsonResponse(fixture.childViewReady);
    }));
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sourceCalculationIdentityDigest={digest}
          initialChild={fixture.childViewReady as never}
          initialCalculation={null}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "검사 상태 새로고침" }));
      await waitFor(() => expect(screen.getAllByText(/검사 완료\(봉인됨\)/).length).toBeGreaterThan(0));
      fireEvent.click(screen.getByRole("button", { name: "V3 계산 요청" }));
      await waitFor(() => expect(screen.getAllByText("마스크 서버의 응답이 지연됩니다.").length).toBeGreaterThan(0));
      fireEvent.click(screen.getByRole("button", { name: "V3 계산 요청" }));
      await waitFor(() => expect(screen.getByText(/독립 마스크 계산 결과/)).toBeTruthy());
      expect(posted.length).toBe(2);
      expect(posted[0]).toEqual(posted[1]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("선언 타임아웃 뒤 재시도는 같은 본문, 파일 변경·성공 뒤 명시적 선언은 새 본문이다", async () => {
    const posted: unknown[] = [];
    let declareCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input);
      if (url.includes("/source-context")) return jsonResponse(fixture.sourceContext);
      if (url.endsWith("/mask-inputs") && init?.method === "POST") {
        declareCalls += 1;
        const body = JSON.parse(init.body as string);
        posted.push(body);
        if (declareCalls === 1) return jsonResponse({ message: "마스크 서버의 응답이 지연됩니다." }, 503);
        const decl = (fixture.childViewPending as { declaration: Record<string, unknown> }).declaration;
        return jsonResponse({
          declaration: { ...decl, declarationId: body.declarationId, maskChildId: body.maskChildId, maskArtifactId: body.maskArtifactId },
          manifest: null,
        }, 201);
      }
      return jsonResponse(fixture.childViewPending);
    }));
    try {
      render(
        <MaskedAnalysisPanel
          {...baseProps}
          sourceCalculationIdentityDigest={digest}
          initialChild={null}
          initialCalculation={null}
        />,
      );
      await setupDeclared();
      await declareWithFile(fileA());
      await waitFor(() => expect(screen.getAllByText("마스크 서버의 응답이 지연됩니다.").length).toBeGreaterThan(0));
      await declareWithFile(fileA());
      await waitFor(() => expect(posted.length).toBe(2));
      expect(posted[0]).toEqual(posted[1]);
      await waitFor(() => expect(screen.getAllByText(/마스크 입력을 선언했습니다/).length).toBeGreaterThan(0));
      // 성공 뒤 명시적 새 선언은 새 자식을 만든다.
      await declareWithFile(fileA());
      await waitFor(() => expect(posted.length).toBe(3));
      expect(posted[2]).not.toEqual(posted[1]);
      // 파일이 바뀌면 새 선언 본문이다.
      await declareWithFile(fileB());
      await waitFor(() => expect(posted.length).toBe(4));
      expect(posted[3]).not.toEqual(posted[2]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("MaskedAnalysisPanel props", () => {
  it("props 변경이 화면을 바꾸고 자동 요청을 만들지 않는다", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    try {
      const { rerender } = render(
        <MaskedAnalysisPanel
          {...baseProps}
          sourceCalculationIdentityDigest={digest}
          initialChild={fixture.childViewReady as never}
          initialCalculation={fixture.detailViewPending as never}
        />,
      );
      expect(screen.queryByText(/독립 마스크 계산 결과/)).toBeNull();
      rerender(
        <MaskedAnalysisPanel
          {...baseProps}
          sourceCalculationIdentityDigest={digest}
          initialChild={fixture.childViewReady as never}
          initialCalculation={fixture.detailViewAvailable as never}
        />,
      );
      expect(screen.getByText(/독립 마스크 계산 결과/)).toBeTruthy();
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
});
