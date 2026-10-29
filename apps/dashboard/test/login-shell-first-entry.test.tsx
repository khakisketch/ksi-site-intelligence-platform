// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
const env = vi.hoisted(() => ({ pathname: "/login", submit: (_next: string) => { void _next; }, reload: () => {}, mounts: 0 }));
vi.mock("next/navigation", () => ({ usePathname: () => env.pathname }));
vi.mock("@/app/login/actions", () => ({login: async (_state: unknown, data: FormData) => { env.submit(String(data.get("next"))); return {}; }}));
vi.mock("@/components/nav/fresh-login-navigation", () => ({loadFreshLoginDestination: () => { env.reload(); return true; }, completeFreshLoginDestination: () => {}, manuallyReloadFreshLoginDestination: () => env.reload()}));
import { AccountDisplayBoundary } from "@/components/nav/AccountDisplayBoundary";
import { LoginForm } from "@/app/login/LoginForm";
const A = `v1-${"a".repeat(64)}`;
const destination = "/sites/site-1/work-areas?workAreaId=area-1#map";
function Protected() { React.useEffect(() => { env.mounts += 1; }, []); return <h1>목적지 현장</h1>; }
function App() {
  const [step, setStep] = React.useState(0);
  React.useEffect(() => {
    env.submit = (next) => { expect(next).toBe(destination); env.pathname = "/sites/site-1/work-areas"; setStep(1); };
    env.reload = () => setStep(2);
  }, []);
  return <AccountDisplayBoundary key={step === 2 ? "fresh" : "login"} fingerprint={step === 2 ? A : null} bypass={step !== 2}>
    {step === 0 ? <LoginForm next={destination} /> : <Protected/>}
  </AccountDisplayBoundary>;
}
beforeEach(() => { env.pathname = "/login"; env.mounts = 0; vi.spyOn(document,"hasFocus").mockReturnValue(true); vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response(JSON.stringify({fingerprint:A})))); });
afterEach(() => {cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();});
it("submits opaque login and opens its original destination in the same tab using a fresh protected snapshot", async () => {
  render(<App/>);
  fireEvent.change(screen.getByLabelText("개발용 Bearer 토큰"), {target:{value:"synthetic-token"}});
  fireEvent.click(screen.getByRole("button",{name:"로그인"}));
  await waitFor(() => expect(screen.getByRole("heading",{name:"목적지 현장"})).toBeTruthy());
  expect(env.mounts).toBe(1);
});

it("never reloads a protected subtree on account changes or route updates", async () => {
  env.pathname = "/sites/site-1/work-areas";
  const reload = vi.fn(); env.reload = reload;
  const view = render(<AccountDisplayBoundary fingerprint={A}><input aria-label="원문" defaultValue="pending" /></AccountDisplayBoundary>);
  await waitFor(() => expect(screen.getByLabelText("원문")).toBeTruthy());
  const input = screen.getByLabelText("원문") as HTMLInputElement;
  fireEvent.change(input,{target:{value:"미완료"}});
  env.pathname = "/login";
  view.rerender(<AccountDisplayBoundary fingerprint={A}><input aria-label="원문" defaultValue="pending" /></AccountDisplayBoundary>);
  env.pathname = "/sites/site-1/work-areas";
  view.rerender(<AccountDisplayBoundary fingerprint={A}><input aria-label="원문" defaultValue="pending" /></AccountDisplayBoundary>);
  fireEvent.blur(window);
  expect(reload).not.toHaveBeenCalled();
  expect(input.isConnected).toBe(true);
  expect(input.value).toBe("미완료");
});

it("keeps a manual recovery action when automatic transition cannot proceed", async () => {
  env.pathname = "/login"; const reload = vi.fn(); env.reload = reload;
  const view = render(<AccountDisplayBoundary fingerprint={null} bypass><div>login</div></AccountDisplayBoundary>);
  env.pathname = "/sites/site-1/work-areas";
  view.rerender(<AccountDisplayBoundary fingerprint={null} bypass><Protected /></AccountDisplayBoundary>);
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(env.mounts).toBe(0);
  fireEvent.click(screen.getByText("이 탭에서 목적지 다시 열기"));
  expect(reload).toHaveBeenCalledTimes(2);
});
