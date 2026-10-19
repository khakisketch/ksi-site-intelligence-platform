/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: mocked.refresh }) }));

import { ActionUnavailable, computeUnavailablePanelPosition } from "@/components/ui/ActionUnavailable";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ToastProvider, useToast } from "@/components/ui/ToastProvider";

beforeAll(() => {
  // jsdom 의 dialog 는 showModal 미지원 — 열림 상태만 흉내낸다.
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.useRealTimers();
});

describe("ActionUnavailable", () => {
  it("막힌 이유를 상시 노출하지 않고 클릭 가능한 버튼만 둔다", () => {
    render(
      <ActionUnavailable label="현장 등록" description="현재 계정으로는 현장을 등록할 수 없습니다." />,
    );
    const trigger = screen.getByRole("button", { name: "현장 등록" });
    expect((trigger as HTMLButtonElement).disabled).toBe(false);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/현재 계정으로는/)).toBeNull();
  });

  it("클릭해야 사유와 안내 닫기가 열리고 설명 클릭은 쓰기를 일으키지 않는다", () => {
    render(
      <ActionUnavailable label="현장 등록" description="현재 계정으로는 현장을 등록할 수 없습니다." />,
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(screen.getByText(/현재 계정으로는/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "안내 닫기" })).toBeTruthy();
    // 링크도 폼도 없다 — 사유 확인 자체는 읽기다.
    expect(document.querySelector("a")).toBeNull();
    expect(mocked.refresh).not.toHaveBeenCalled();
  });

  it("안내 닫기로 닫으면 트리거로 포커스가 돌아온다", () => {
    render(<ActionUnavailable label="현장 등록" description="사유" />);
    const trigger = screen.getByRole("button", { name: "현장 등록" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "안내 닫기" }));
    expect(screen.queryByText("사유")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("Escape 으로 닫히고 트리거로 포커스가 돌아온다", () => {
    render(<ActionUnavailable label="현장 등록" description="사유" />);
    const trigger = screen.getByRole("button", { name: "현장 등록" });
    fireEvent.click(trigger);
    expect(screen.getByText("사유")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("사유")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("바깥 클릭으로 닫힌다", () => {
    render(<ActionUnavailable label="현장 등록" description="사유" />);
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(screen.getByText("사유")).toBeTruthy();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByText("사유")).toBeNull();
  });

  it("retry 면 권한 다시 확인이 router.refresh 로 읽는다", () => {
    render(<ActionUnavailable label="현장 등록" description="미확인" retry />);
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    fireEvent.click(screen.getByRole("button", { name: "권한 다시 확인" }));
    expect(mocked.refresh).toHaveBeenCalledTimes(1);
  });

  it("retry 가 아니면 재확인 버튼을 두지 않는다", () => {
    render(<ActionUnavailable label="현장 등록" description="거부" />);
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(screen.queryByRole("button", { name: "권한 다시 확인" })).toBeNull();
  });

  it("네이티브 팝오버 최상위 레이어로 열어 overflow-hidden 조상에 잘리지 않는다", () => {
    render(
      <div style={{ overflow: "hidden" }}>
        <ActionUnavailable label="현장 등록" description="사유" />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    const panel = screen.getByText("사유").closest("div[id]") as HTMLElement;
    expect(panel?.getAttribute("popover")).toBe("manual");
  });

  it("열 때 측정 좌표로 배치한다(뒤집기·고정은 단위 테스트)", () => {
    render(<ActionUnavailable label="현장 등록" description="사유" />);
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    const panel = screen.getByText("사유").closest("div[id]") as HTMLElement;
    // jsdom rect·크기는 0이라 여백 8px 원점으로 고정된다 — 배치 코드가 돈 증거다.
    expect(panel?.style.top).toBe("8px");
    expect(panel?.style.left).toBe("8px");
  });

  it("트리거를 다시 누르면 포커스를 둔 채로 닫는다", () => {
    render(<ActionUnavailable label="현장 등록" description="사유" />);
    const trigger = screen.getByRole("button", { name: "현장 등록" });
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByText("사유")).toBeTruthy();
    fireEvent.click(trigger);
    expect(screen.queryByText("사유")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("computeUnavailablePanelPosition", () => {
  const viewport = { width: 1024, height: 768 };
  const panel = { width: 256, height: 120 };

  it("오른쪽 끝 트리거도 화면 안에 들어오게 왼쪽으로 고정한다", () => {
    const pos = computeUnavailablePanelPosition(
      { top: 100, bottom: 136, left: 900, right: 1000 },
      panel,
      viewport,
    );
    expect(pos.left + 256).toBeLessThanOrEqual(1024 - 8);
    expect(pos.top).toBe(136 + 8);
  });

  it("왼쪽 끝 트리거에서 x<0 으로 나가지 않는다", () => {
    const pos = computeUnavailablePanelPosition(
      { top: 100, bottom: 136, left: 4, right: 60 },
      panel,
      viewport,
    );
    expect(pos.left).toBeGreaterThanOrEqual(8);
  });

  it("아래가 막히면 위로 뒤집는다", () => {
    const pos = computeUnavailablePanelPosition(
      { top: 700, bottom: 736, left: 500, right: 600 },
      panel,
      viewport,
    );
    expect(pos.top).toBe(700 - 8 - 120);
    expect(pos.top + 120).toBeLessThanOrEqual(768 - 8);
  });

  it("위·아래가 다 막히면 화면 안에 고정한다", () => {
    const pos = computeUnavailablePanelPosition(
      { top: 300, bottom: 336, left: 500, right: 600 },
      { width: 256, height: 900 },
      viewport,
    );
    expect(pos.top).toBeGreaterThanOrEqual(8);
    expect(pos.top).toBeLessThanOrEqual(768 - 8);
  });

  it("모바일 좁은 화면에서 패널이 화면보다 넓어지지 않는다", () => {
    const pos = computeUnavailablePanelPosition(
      { top: 100, bottom: 136, left: 8, right: 120 },
      panel,
      { width: 360, height: 640 },
    );
    expect(pos.left).toBeGreaterThanOrEqual(8);
    expect(pos.left + Math.min(256, 360 - 16)).toBeLessThanOrEqual(360 - 8);
  });
});

describe("ToastProvider", () => {
  function Notifier({ message }: { message: string }) {
    const { notify } = useToast();
    return (
      <button type="button" onClick={() => notify(message)}>
        띄우기
      </button>
    );
  }

  it("Provider 없이 써도 조용히 무시된다(레거시 독립 렌더 안전망)", () => {
    render(<Notifier message="됐습니다" />);
    fireEvent.click(screen.getByRole("button", { name: "띄우기" }));
    expect(screen.queryByText("됐습니다")).toBeNull();
  });

  it("성공 한 마디를 띄우고 알림 닫기로 닫는다", () => {
    render(
      <ToastProvider>
        <Notifier message="저장했습니다" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "띄우기" }));
    expect(screen.getByText("저장했습니다")).toBeTruthy();
    // role=status aria-live 영역은 하나뿐이다.
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "알림 닫기" })).toBeTruthy();
    // 포커스를 빼앗지 않는다 — 토스트 영역 안으로 초점이 가지 않는다.
    expect(screen.getByRole("status").contains(document.activeElement)).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "알림 닫기" }));
    expect(screen.queryByText("저장했습니다")).toBeNull();
  });

  it("최신 1개만 보이고 6초 뒤에 사라진다", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Notifier message="둘째" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "띄우기" }));
    expect(screen.getByText("둘째")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(5999);
    });
    expect(screen.getByText("둘째")).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("둘째")).toBeNull();
  });

  it("가리키는 동안 타이머가 멈춘다", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <Notifier message="머뭄" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "띄우기" }));
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    fireEvent.mouseEnter(screen.getByRole("status"));
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("머뭄")).toBeTruthy();
    fireEvent.mouseLeave(screen.getByRole("status"));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.queryByText("머뭄")).toBeNull();
  });

  it("숨김 탭에서 띄우면 멈춘 채로 두고 복귀 후 최소 노출을 지킨다", () => {
    vi.useFakeTimers();
    const hiddenDescriptor = Object.getOwnPropertyDescriptor(document, "hidden");
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    try {
      render(
        <ToastProvider>
          <Notifier message="숨김" />
        </ToastProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "띄우기" }));
      act(() => {
        vi.advanceTimersByTime(6000);
      });
      // 멈춤 환경에서 교체돼도 타이머 없이 그대로 있다.
      expect(screen.getByText("숨김")).toBeTruthy();
      Object.defineProperty(document, "hidden", { configurable: true, value: false });
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      act(() => {
        vi.advanceTimersByTime(5999);
      });
      expect(screen.getByText("숨김")).toBeTruthy();
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(screen.queryByText("숨김")).toBeNull();
    } finally {
      if (hiddenDescriptor) Object.defineProperty(document, "hidden", hiddenDescriptor);
    }
  });
});

describe("ConfirmDialog", () => {
  it("닫혀 있으면 내용을 렌더하지 않는다", () => {
    render(
      <ConfirmDialog
        open={false}
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByText("현장 삭제")).toBeNull();
  });

  it("열리면 취소에 기본 포커스를 두고 확인은 명시적 라벨이다", () => {
    render(
      <ConfirmDialog
        open
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "취소" }));
    expect(screen.getByRole("button", { name: "현장 삭제" })).toBeTruthy();
  });

  it("확인·취소가 각 핸들러만 실행한다", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = render(
      <ConfirmDialog
        open
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 삭제" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    rerender(
      <ConfirmDialog
        open={false}
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
  });

  it("Escape(cancel 이벤트)은 취소만 실행한다", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    const dialog = document.querySelector("dialog");
    expect(dialog).toBeTruthy();
    fireEvent(dialog!, new Event("cancel", { cancelable: true }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("pending 이면 확인이 막혀 중복 실행되지 않는다", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={onConfirm}
        onCancel={() => {}}
        pending
      />,
    );
    const confirm = screen.getByRole("button", { name: "처리 중…" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("닫히면 트리거로 포커스가 돌아온다", () => {
    const onCancel = vi.fn();
    function Harness({ open }: { open: boolean }) {
      return (
        <>
          <button type="button">트리거</button>
          <ConfirmDialog
            open={open}
            title="현장 삭제"
            description="되돌릴 수 없습니다."
            confirmLabel="현장 삭제"
            onConfirm={() => {}}
            onCancel={onCancel}
          />
        </>
      );
    }
    const { rerender } = render(<Harness open={false} />);
    const trigger = screen.getByRole("button", { name: "트리거" });
    trigger.focus();
    rerender(<Harness open />);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "취소" }));
    rerender(<Harness open={false} />);
    expect(document.activeElement).toBe(trigger);
  });

  it("제목·설명을 고유 id 로 연결하고 여러 개가 겹치지 않는다", () => {
    render(
      <>
        <ConfirmDialog
          open
          title="첫째 삭제"
          description="첫째 설명"
          confirmLabel="첫째 삭제"
          onConfirm={() => {}}
          onCancel={() => {}}
        />
        <ConfirmDialog
          open
          title="둘째 삭제"
          description="둘째 설명"
          confirmLabel="둘째 삭제"
          onConfirm={() => {}}
          onCancel={() => {}}
        />
      </>,
    );
    const dialogs = document.querySelectorAll("dialog");
    expect(dialogs).toHaveLength(2);
    const labelledBy = [dialogs[0].getAttribute("aria-labelledby"), dialogs[1].getAttribute("aria-labelledby")];
    const describedBy = [dialogs[0].getAttribute("aria-describedby"), dialogs[1].getAttribute("aria-describedby")];
    expect(labelledBy[0]).toBeTruthy();
    expect(labelledBy[0]).not.toBe(labelledBy[1]);
    expect(describedBy[0]).not.toBe(describedBy[1]);
    for (const [dialog, labelled, described] of [
      [dialogs[0], labelledBy[0], describedBy[0]],
      [dialogs[1], labelledBy[1], describedBy[1]],
    ] as const) {
      expect(document.getElementById(labelled!)?.textContent).toMatch(/삭제/);
      expect(document.getElementById(described!)?.textContent).toMatch(/설명/);
      expect(dialog.contains(document.getElementById(labelled!))).toBe(true);
    }
  });

  it("부모 리렌더 전 연타도 한 번만 실행한다", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );
    const confirm = screen.getByRole("button", { name: "현장 삭제" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    fireEvent.keyDown(confirm, { key: "Enter" });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("pending 중 취소는 그대로 동작하고 실행을 일으키지 않는다", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={onConfirm}
        onCancel={onCancel}
        pending
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "취소" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("배경 클릭은 취소와 같고 결정을 실행하지 않는다", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="현장 삭제"
        description="되돌릴 수 없습니다."
        confirmLabel="현장 삭제"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    const dialog = document.querySelector("dialog")!;
    fireEvent.click(dialog);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
