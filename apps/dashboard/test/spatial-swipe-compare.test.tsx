/** @vitest-environment jsdom */
import { createElement } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MaterialsDesignPreview from "@/app/design-preview/materials/MaterialsDesignPreview";
import { SpatialSwipeCompare } from "@/components/site/SpatialSwipeCompare";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    createElement("a", { href, ...props }, children),
}));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function binding() {
  return {
    frame: {
      onPointerDown: vi.fn(),
      onPointerMove: vi.fn(),
      onPointerUp: vi.fn(),
      onPointerCancel: vi.fn(),
      onLostPointerCapture: vi.fn(),
      onDoubleClick: vi.fn(),
      onKeyDown: vi.fn(),
    },
    ref: vi.fn(),
    contentRef: vi.fn(),
  };
}

function renderSwipe(boundary = 50, onBoundaryChange = vi.fn(), refCleanup?: () => void) {
  const bound = binding();
  if (refCleanup) bound.ref.mockReturnValue(refCleanup);
  const view = render(
    <SpatialSwipeCompare
      frameProps={{
        ref: bound.ref,
        tabIndex: 0,
        role: "group",
        onPointerDown: bound.frame.onPointerDown,
        onPointerMove: bound.frame.onPointerMove,
        onPointerUp: bound.frame.onPointerUp,
        onPointerCancel: bound.frame.onPointerCancel,
        onLostPointerCapture: bound.frame.onLostPointerCapture,
        onDoubleClick: bound.frame.onDoubleClick,
        onKeyDown: bound.frame.onKeyDown,
        style: { touchAction: "none" as const },
        "aria-label": "밀어서 비교",
      }}
      contentRef={bound.contentRef}
      contentStyle={{ transform: "translate(10%, 5%) scale(2)", transformOrigin: "0 0" }}
      aspectRatio="1100 / 985"
      left={
        /* eslint-disable-next-line @next/next/no-img-element -- test-only pixels */
        <img src="/a.webp" alt="" />
      }
      right={
        /* eslint-disable-next-line @next/next/no-img-element -- test-only pixels */
        <img src="/b.webp" alt="" />
      }
      leftLabel="A 2021-08-17"
      rightLabel="B 2022-08-24"
      boundary={boundary}
      onBoundaryChange={onBoundaryChange}
    />,
  );
  return { ...view, bound, onBoundaryChange };
}

describe("swipe viewport structure", () => {
  it("retains the viewport callback-ref cleanup so wheel listeners cannot accumulate", () => {
    const cleanupRef = vi.fn();
    const { unmount } = renderSwipe(50, vi.fn(), cleanupRef);
    unmount();
    expect(cleanupRef).toHaveBeenCalledTimes(1);
  });
  it("layers both visuals with one shared transform and a screen-space clip", () => {
    const { container } = renderSwipe();
    const slider = screen.getByRole("slider", { name: "비교 경계" });
    expect(slider.getAttribute("aria-valuemin")).toBe("0");
    expect(slider.getAttribute("aria-valuemax")).toBe("100");
    expect(slider.getAttribute("aria-valuenow")).toBe("50");
    expect(slider.getAttribute("aria-valuetext")).toBe("A 2021-08-17 50% · B 2022-08-24 50%");
    // 같은 transform이 두 층에 그대로 걸린다.
    const transformed = container.querySelectorAll('[style*="scale(2)"]');
    expect(transformed.length).toBe(2);
    // 클립은 변환된 층 밖에 둔다.
    const clip = container.querySelector('[style*="clip-path"]') as HTMLElement | null;
    expect(clip?.style.clipPath).toBe("inset(0 50% 0 0)");
  });

  // jsdom PointerEvent는 clientX 초기값을 흘리지 않으므로 MouseEvent로
  // 같은 타입명을 직접 쏜다 — React는 타입명으로 듣는다.
  function pointerEvent(type: string, init: Record<string, unknown> & { pointerType?: string }) {
    const { pointerType, pointerId = 1, ...rest } = init;
    const event = new window.MouseEvent(type, { bubbles: true, cancelable: true, ...rest });
    Object.defineProperty(event, "pointerType", { value: pointerType ?? "mouse" });
    Object.defineProperty(event, "pointerId", { value: pointerId });
    return event;
  }

  it("moves the boundary by grip drag without panning the shared map", () => {
    const { bound, onBoundaryChange } = renderSwipe(50);
    const grip = screen.getByRole("slider", { name: "비교 경계" });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 400, 300));
    grip.dispatchEvent(pointerEvent("pointerdown", { pointerType: "mouse", button: 0, clientX: 200 }));
    grip.dispatchEvent(pointerEvent("pointermove", { clientX: 240 }));
    expect(onBoundaryChange).toHaveBeenLastCalledWith(60);
    expect(bound.frame.onPointerDown).not.toHaveBeenCalled();
    expect(bound.frame.onPointerMove).not.toHaveBeenCalled();
    grip.dispatchEvent(pointerEvent("pointerup", { clientX: 240 }));
    grip.dispatchEvent(pointerEvent("pointermove", { clientX: 400 }));
    expect(onBoundaryChange).toHaveBeenCalledTimes(1);
  });

  it("cancels the drag without committing a jump", () => {
    const { onBoundaryChange } = renderSwipe(30);
    const grip = screen.getByRole("slider", { name: "비교 경계" });
    grip.dispatchEvent(pointerEvent("pointerdown", { pointerType: "touch", clientX: 120 }));
    grip.dispatchEvent(pointerEvent("pointercancel", { pointerType: "touch", clientX: 300 }));
    grip.dispatchEvent(pointerEvent("pointermove", { pointerType: "touch", clientX: 300 }));
    expect(onBoundaryChange).not.toHaveBeenCalled();
  });

  it("ends a grip interaction on lost capture and does not double-click zoom the image", () => {
    const { bound, onBoundaryChange } = renderSwipe(30);
    const grip = screen.getByRole("slider", { name: "비교 경계" });
    grip.dispatchEvent(pointerEvent("pointerdown", { clientX: 120 }));
    grip.dispatchEvent(pointerEvent("lostpointercapture", { clientX: 120 }));
    grip.dispatchEvent(pointerEvent("pointermove", { clientX: 180 }));
    fireEvent.doubleClick(grip);
    expect(onBoundaryChange).not.toHaveBeenCalled();
    expect(bound.frame.onDoubleClick).not.toHaveBeenCalled();
  });

  it("drives the boundary by slider keys apart from map panning", () => {
    const { bound, onBoundaryChange } = renderSwipe(50);
    const grip = screen.getByRole("slider", { name: "비교 경계" });
    fireEvent.keyDown(grip, { key: "ArrowRight" });
    expect(onBoundaryChange).toHaveBeenLastCalledWith(51);
    fireEvent.keyDown(grip, { key: "ArrowLeft", shiftKey: true });
    expect(onBoundaryChange).toHaveBeenLastCalledWith(40);
    fireEvent.keyDown(grip, { key: "Home" });
    expect(onBoundaryChange).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(grip, { key: "End" });
    expect(onBoundaryChange).toHaveBeenLastCalledWith(100);
    fireEvent.keyDown(grip, { key: "Enter" });
    expect(onBoundaryChange).toHaveBeenCalledTimes(4);
    // 비교 키가 아니면 그립이 막지 않고 공유 뷰포트로 넘긴다 — 훅이 무시한다.
    expect(bound.frame.onKeyDown).toHaveBeenCalledTimes(1);
  });
});

describe("example swipe integration", () => {
  it("switches modes without losing the selected dates", () => {
    render(<MaterialsDesignPreview />);
    fireEvent.click(screen.getByRole("button", { name: "밀어서 비교" }));
    expect(screen.getByRole("slider", { name: "비교 경계" })).toBeDefined();
    expect((screen.getByLabelText("A 관측 선택") as HTMLSelectElement).value).toBe("obs-2021");
    expect((screen.getByLabelText("B 관측 선택") as HTMLSelectElement).value).toBe("obs-2022");
    fireEvent.click(screen.getByRole("button", { name: "나란히" }));
    expect(screen.queryByRole("slider", { name: "비교 경계" })).toBeNull();
    expect((screen.getByLabelText("A 관측 선택") as HTMLSelectElement).value).toBe("obs-2021");
  });

  it("asks for one shared layer instead of silently changing kinds", () => {
    render(<MaterialsDesignPreview />);
    fireEvent.click(screen.getByRole("group", { name: "A 층 선택" }).querySelector("button:last-child") as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "밀어서 비교" }));
    expect(screen.getByText("두 칸의 층이 다릅니다")).toBeDefined();
    expect(screen.queryByRole("slider", { name: "비교 경계" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "둘 다 DSM으로" }));
    expect(screen.getByRole("slider", { name: "비교 경계" })).toBeDefined();
  });

  it("notes the same observation on both sides without changing values", () => {
    render(<MaterialsDesignPreview />);
    fireEvent.click(screen.getByRole("button", { name: "밀어서 비교" }));
    fireEvent.change(screen.getByLabelText("B 관측 선택"), { target: { value: "obs-2021" } });
    expect(screen.getByText("같은 관측을 두 번 선택했습니다. 같은 사진이 양쪽에 겹쳐 보입니다.")).toBeDefined();
    expect((screen.getByLabelText("A 관측 선택") as HTMLSelectElement).value).toBe("obs-2021");
    expect((screen.getByLabelText("B 관측 선택") as HTMLSelectElement).value).toBe("obs-2021");
  });
});
