/** @vitest-environment jsdom */
import { renderToStaticMarkup } from "react-dom/server";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const formPropsSeen: Array<Record<string, unknown>> = [];

vi.mock("next/form", () => ({
  default: function MockForm(props: Record<string, unknown>) {
    const { scroll, replace, ...rest } = props as {
      scroll?: unknown;
      replace?: unknown;
    } & Record<string, unknown>;
    formPropsSeen.push({ scroll, replace, hasMethod: "method" in rest });
    return <form {...(rest as React.FormHTMLAttributes<HTMLFormElement>)} />;
  },
}));

import { SiteSelectionForm } from "@/app/sites/[siteId]/SiteSelectionForm";

const SUBMIT = HTMLFormElement.prototype.requestSubmit;

beforeEach(() => {
  formPropsSeen.length = 0;
  window.history.pushState({}, "", "/sites/site-a?workAreaId=w1&assetRef=a");
  document.body.focus();
  // requestSubmit 대신 submit 이벤트를 그대로 흘려서 onSubmit 경로를 탄다.
  HTMLFormElement.prototype.requestSubmit = function (this: HTMLFormElement) {
    this.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  } as typeof SUBMIT;
});

afterEach(() => {
  cleanup();
  HTMLFormElement.prototype.requestSubmit = SUBMIT;
  vi.restoreAllMocks();
});

function workspaceForm() {
  return (
    <SiteSelectionForm action="/sites/site-a" className="sel">
      <input type="hidden" name="workAreaId" value="w1" />
      <label htmlFor="workspace-capture">관측 시점</label>
      <select id="workspace-capture" name="assetRef" defaultValue="a">
        <option value="a">관측 A</option>
        <option value="b">관측 B</option>
      </select>
    </SiteSelectionForm>
  );
}

describe("SiteSelectionForm", () => {
  it("GET 쿼리·히스토리·no-JS 경로를 그대로 둔다", () => {
    const html = renderToStaticMarkup(workspaceForm());
    expect(html).toContain('action="/sites/site-a"');
    // method 속성을 두지 않는다 — 네이티브 기본 GET 이며 next/form 도 method 를 금지한다.
    expect(html).not.toContain("method=");
    expect(html).toContain('name="workAreaId"');
    expect(html).toContain('name="assetRef"');
    // SSR(no-JS)에서는 제출 단추가 보이고 눌린다.
    expect(html).toContain('type="submit"');
    expect(html).toContain('<button type="submit" class="btn">보기</button>');
    expect(html).not.toContain("hidden=");
    expect(html).not.toContain("disabled");
  });

  it("클라이언트 이동으로 제출하고 위로 올리지 않는다", () => {
    const { container } = render(workspaceForm());
    expect(formPropsSeen.length).toBeGreaterThan(0);
    const last = formPropsSeen[formPropsSeen.length - 1]!;
    expect(last.scroll).toBe(false);
    expect(last.replace).toBeUndefined();
    expect(last.hasMethod).toBe(false);
    // 문서·no-JS 계약용 GET 표시는 DOM 속성에 둔다.
    expect(container.querySelector("form")?.getAttribute("method")).toBe("get");
  });

  it("select 변경에만 즉시 제출한다(필수 빈값·텍스트 입력 제외)", () => {
    const { container } = render(
      <SiteSelectionForm action="/sites/site-a">
        <select id="req-area" name="workAreaId" defaultValue="w1" required aria-label="작업구역">
          <option value="">선택</option>
          <option value="w1">구역 1</option>
          <option value="w2">구역 2</option>
        </select>
        <input id="q" name="q" type="search" defaultValue="" aria-label="검색" />
      </SiteSelectionForm>,
    );
    const requestSubmit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit");
    const area = container.querySelector("#req-area") as HTMLSelectElement;
    const q = container.querySelector("#q") as HTMLInputElement;

    fireEvent.change(q, { target: { value: "곰" } });
    expect(requestSubmit).not.toHaveBeenCalled();

    fireEvent.change(area, { target: { value: "" } });
    expect(requestSubmit).not.toHaveBeenCalled();

    fireEvent.change(area, { target: { value: "w2" } });
    expect(requestSubmit).toHaveBeenCalledTimes(1);
  });

  it("조합 중에는 제출하지 않고 조합이 끝나면 한 번만 제출한다", () => {
    const { container } = render(workspaceForm());
    const requestSubmit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit");
    const select = container.querySelector("#workspace-capture") as HTMLSelectElement;

    fireEvent.compositionStart(select);
    fireEvent.change(select, { target: { value: "b" } });
    expect(requestSubmit).not.toHaveBeenCalled();

    fireEvent.compositionEnd(select);
    expect(requestSubmit).toHaveBeenCalledTimes(1);
  });

  it("마운트만으로 초점을 훔치지 않고 제출하지도 않는다", () => {
    const requestSubmit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit");
    render(workspaceForm());
    expect(document.activeElement).toBe(document.body);
    expect(requestSubmit).not.toHaveBeenCalled();
  });

  it("제출 뒤 이동이 끝나고 폼이 다시 그려지면 같은 컨트롤로 초점이 돌아온다", async () => {
    const focusSpy = vi.spyOn(HTMLElement.prototype, "focus");
    const first = render(workspaceForm());
    const select = first.container.querySelector("#workspace-capture") as HTMLSelectElement;
    (select as HTMLElement).focus();
    expect(document.activeElement).toBe(select);
    focusSpy.mockClear();

    // 변경 → requestSubmit → submit. 이동 전에는 아직 같은 URL 이다.
    fireEvent.change(select, { target: { value: "b" } });

    // 전체 리로드였다면 초점은 body 로 떨어진다. 클라이언트 이동 뒤 호출자가
    // 새 선택값으로 폼을 다시 그리는 것을 unmount/remount 로 흉내낸다.
    (document.activeElement as HTMLElement).blur();
    expect(document.activeElement).toBe(document.body);
    first.unmount();

    window.history.pushState({}, "", "/sites/site-a?workAreaId=w1&assetRef=b");
    const second = render(workspaceForm());
    const next = second.container.querySelector("#workspace-capture") as HTMLSelectElement;

    await waitFor(() => expect(document.activeElement).toBe(next));
    expect(focusSpy).toHaveBeenCalledTimes(1);
  });

  it("이동이 없으면 초점을 옮기지 않는다", async () => {
    const focusSpy = vi.spyOn(HTMLElement.prototype, "focus");
    const { container } = render(workspaceForm());
    const select = container.querySelector("#workspace-capture") as HTMLSelectElement;
    (select as HTMLElement).focus();
    fireEvent.change(select, { target: { value: "b" } });
    focusSpy.mockClear();
    // 같은 URL 로 다시 그려져도(효과 재실행 없음) 초점을 건드리지 않는다.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(document.activeElement).toBe(select);
    expect(focusSpy).not.toHaveBeenCalled();
  });

  it("사용자가 폼 밖으로 초점을 옮겼으면 느린 이동 뒤에도 끌어오지 않는다", async () => {
    const first = render(workspaceForm());
    const select = first.container.querySelector("#workspace-capture") as HTMLSelectElement;
    (select as HTMLElement).focus();
    fireEvent.change(select, { target: { value: "b" } });

    // 느린 이동 중에 사용자가 바깥으로 탭 이동.
    fireEvent.blur(select, { relatedTarget: document.body });
    (document.activeElement as HTMLElement).blur();
    first.unmount();

    window.history.pushState({}, "", "/sites/site-a?workAreaId=w1&assetRef=b");
    render(workspaceForm());

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(document.activeElement).toBe(document.body);
  });

  it("Back/앞으로(popstate) 뒤에는 초점을 훔치지 않는다", async () => {
    const first = render(workspaceForm());
    const select = first.container.querySelector("#workspace-capture") as HTMLSelectElement;
    (select as HTMLElement).focus();
    fireEvent.change(select, { target: { value: "b" } });
    (document.activeElement as HTMLElement).blur();
    first.unmount();

    // Back: popstate 가 인계를 먼저 버린다.
    window.dispatchEvent(new PopStateEvent("popstate"));
    window.history.pushState({}, "", "/sites/site-a?workAreaId=w1&assetRef=a");
    render(workspaceForm());

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(document.activeElement).toBe(document.body);
  });

  it("인계 없이 일어난 이동에서는 초점을 훔치지 않는다", async () => {
    render(workspaceForm());
    expect(document.activeElement).toBe(document.body);
    window.history.pushState({}, "", "/sites/site-a?workAreaId=w1&assetRef=b");
    const { container } = render(workspaceForm());
    expect(container.querySelector("#workspace-capture")).not.toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(document.activeElement).toBe(document.body);
  });
});
