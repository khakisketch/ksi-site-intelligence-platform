/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDraftState } from "@/hooks/useDraftState";

const KEY = "synthetic-draft-preservation";
const INITIAL = { name: "" };

function Probe({ storageKey = KEY, migrate }: { storageKey?: string; migrate?: (stored: unknown) => typeof INITIAL }) {
  const [draft, setDraft, , storageStatus] = useDraftState(storageKey, INITIAL, migrate);
  return (
    <>
      <p data-testid="storage-status">{storageStatus}</p>
      <input aria-label="draft name" value={draft.name} onChange={(event) => setDraft({ name: event.target.value })} />
    </>
  );
}

describe("draft storage preservation", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it.each(["", '{"origin":"unknown",'])(
    "does not overwrite unreadable stored bytes on mount or subsequent edits",
    (raw) => {
      sessionStorage.setItem(KEY, raw);
      render(<StrictMode><Probe /></StrictMode>);

      expect(sessionStorage.getItem(KEY)).toBe(raw);
      expect(screen.getByTestId("storage-status").textContent).toBe("unreadable");
      fireEvent.change(screen.getByLabelText("draft name"), { target: { value: "new input" } });
      expect(sessionStorage.getItem(KEY)).toBe(raw);

      cleanup();
      render(<Probe />);
      expect(screen.getByTestId("storage-status").textContent).toBe("unreadable");
      expect(sessionStorage.getItem(KEY)).toBe(raw);
    },
  );

  it("still saves and restores a normal draft", () => {
    render(<Probe />);
    expect(screen.getByTestId("storage-status").textContent).toBe("ready");
    fireEvent.change(screen.getByLabelText("draft name"), { target: { value: "known input" } });
    expect(JSON.parse(sessionStorage.getItem(KEY)!)).toEqual({ name: "known input" });

    cleanup();
    render(<Probe />);
    expect((screen.getByLabelText("draft name") as HTMLInputElement).value).toBe("known input");
  });

  it("preserves the last edit even if the component unmounts in the same event batch", () => {
    const view = render(<Probe />);
    const input = screen.getByLabelText("draft name");
    act(() => {
      fireEvent.change(input, { target: { value: "last raw edit" } });
      view.unmount();
    });
    expect(JSON.parse(sessionStorage.getItem(KEY)!)).toEqual({ name: "last raw edit" });
    render(<Probe />);
    expect((screen.getByLabelText("draft name") as HTMLInputElement).value).toBe("last raw edit");
  });

  it("preserves valid JSON when its stored shape cannot be migrated", () => {
    const raw = JSON.stringify({ unrecognized: "original" });
    const reject = () => { throw new Error("unrecognized draft"); };
    sessionStorage.setItem(KEY, raw);
    render(<Probe migrate={reject} />);
    expect(sessionStorage.getItem(KEY)).toBe(raw);
    expect(screen.getByTestId("storage-status").textContent).toBe("unreadable");
  });

  it("does not rewrite a readable original merely by migrating and opening it", () => {
    const raw = '{ "name": "known input", "futureField": "original" }';
    sessionStorage.setItem(KEY, raw);
    const migrate = (stored: unknown) => ({ name: (stored as { name: string }).name });
    render(<Probe migrate={migrate} />);
    expect((screen.getByLabelText("draft name") as HTMLInputElement).value).toBe("known input");
    expect(sessionStorage.getItem(KEY)).toBe(raw);
    cleanup();
    render(<Probe migrate={migrate} />);
    expect(sessionStorage.getItem(KEY)).toBe(raw);
  });

  it("does not copy the old state to an empty newly selected key", () => {
    sessionStorage.setItem(KEY, JSON.stringify({ name: "first draft" }));
    const { rerender } = render(<Probe />);
    expect((screen.getByLabelText("draft name") as HTMLInputElement).value).toBe("first draft");
    rerender(<Probe storageKey={`${KEY}-other`} />);
    expect(sessionStorage.getItem(`${KEY}-other`)).toBeNull();
    expect(JSON.parse(sessionStorage.getItem(KEY)!)).toEqual({ name: "first draft" });
  });

  it("reports a write failure rather than claiming the draft was saved", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    render(<Probe />);
    fireEvent.change(screen.getByLabelText("draft name"), { target: { value: "unsaved input" } });
    expect(screen.getByTestId("storage-status").textContent).toBe("write-failed");
  });

  it("does not write if the previous storage value could not be read", () => {
    sessionStorage.setItem(KEY, '{"unread":"original"}');
    const write = vi.spyOn(Storage.prototype, "setItem");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    render(<Probe />);
    expect(screen.getByTestId("storage-status").textContent).toBe("unavailable");
    expect(write).not.toHaveBeenCalled();
  });
});
