import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";
import { join } from "node:path";

import {
  isLoopbackHostname,
  requireLoopbackOnlyInterfaces,
} from "./fixtures/owner-journey-network-guard";

// Owner-journey synthetic probe — explicitly synthetic, portable, task-owned fixture-only.
//
// Provenance: converted in place from the prior untracked local probe
// (`zz-owner-journey-probe.spec.ts`, 2026-10-28). The original performed real
// registration mutations while writing screenshots to a fixed
// `/tmp/opencode/ksi-owner-journey-20261028/shots` path and reading its
// GeoTIFF from another fixed `/tmp` path at module import time. The original
// input was 8192 zero bytes with a TIFF magic header — not a valid image and
// not customer data. This version preserves the meaningful journey assertions
// and replaces every machine-specific path with test-owned input/output.
//
// Synthetic identity (no customer data):
// - The uploaded "GeoTIFF" is deterministic synthetic bytes built in memory
//   (`syntheticOrthoFile()`): a TIFF magic prefix plus an ASCII marker. It is
//   not a real GeoTIFF, not a field capture, and not derived from any customer
//   file. The registration client hashes whatever bytes it is given, so the
//   "확인 완료" step works the same as with the original zero file; the Core
//   seal step cannot succeed on this fixture and the test asserts the honest
//   uncertain outcome as-is (see capability boundary below).
// - All screenshots and JSON logs go to Playwright's test-owned output
//   (`testInfo.outputPath`) and are attached to the report. Nothing is written
//   to `/tmp/opencode/...` or any other fixed machine path, so pre-existing
//   evidence from the original probe run is never overwritten or deleted.
//
// Fixture capability boundary (this run revalidates post-fix behavior):
// - The shared config's auto-started stack (`webServer`,
//   `reuseExistingServer: false`) has no evidence-storage (S3) configuration,
//   so the seal cannot succeed here. What the BFF returns and what the user
//   sees is verified by execution in this run — never inferred from the
//   pre-fix uncaught-500 observation, which is discarded. The unconfigured-
//   storage failure path now carries another lead's genuine fail-closed fix
//   (`STORAGE_UNAVAILABLE` HTTP 503, foreign scope 404, no new journal
//   record); this execution revalidates the end-to-end surface against that
//   corrected behavior. No positive seal path is covered: the upload input is
//   a synthetic dummy (`syntheticOrthoFile`), and a sealed revision is
//   scope-excluded (recorded in the JSON log, never simulated).
// - The original probe's seal OR (success/failure) never matched this stack's
//   actual third outcome (uncertain), and its own evidence (no screenshots past
//   registration fill) confirms it never got past the seal step.
//
// Mutation safety: this probe is disabled regardless of environment or
// Playwright config until an independently verified, task-owned isolated runner
// exists. A loopback-only interface list and familiar fixture labels do not
// prove network isolation or ownership of an arbitrary local service. The
// retained dedicated configuration also refuses before starting a webServer.
// A different Playwright config can start its webServer before evaluating a
// spec skip; do not run this diagnostic through the shared config as an
// isolation check. Its previous network-none browser run used an image built
// with unauthorized network/package access and is historical evidence only.
//
// Network:
// - The loopback-only tripwire above is a precondition, not enforcement of
//   isolation. The in-page browser-context guard (`context.route`, installed
//   in the same `beforeEach` AFTER the tripwire passes) is additional
//   defense-in-depth only — it is NOT authorization and NOT OS-level
//   isolation.
// - Documented interception limits (per official Playwright network docs, and
//   the reason the browser filter cannot authorize anything): route handlers
//   fire only for the FIRST URL of a redirect chain — Chromium/Firefox follow
//   subsequent redirects without invoking the handler — so a loopback-first
//   redirect landing externally would NOT be aborted; and a registered service
//   worker can bypass interception entirely (none is registered by this app,
//   verified by source grep, but the guard cannot prove that invariant holds).
//   Fault-injection routes are page-level with named handlers removed by
//   targeted `unroute` only, so the context guard is never lifted mid-test.
// - The guard therefore aborts only directly-issued non-loopback http(s)
//   requests. Normal map tiles (e.g. OSM) are blocked by it; affected
//   assertions are layout/overflow/axe only and do not depend on tile bytes.
// - The guard proves itself for directly-issued HTTP(S) navigations/requests:
//   each test first navigates to a reserved non-loopback URL
//   (`http://example.invalid/`, RFC 2606) and requires the browser to abort
//   with BLOCKED_BY_CLIENT. That single check proves only that the HTTP(S)
//   interception is armed — not that every external listener, redirect
//   target, websocket, or service worker is unreachable. If that self-check
//   ever passes or fails differently, the test fails closed.
// - An OS network namespace was attempted in this container and is
//   UNAVAILABLE (`unshare` uid_map EPERM, `bwrap` RTM_NEWADDR EPERM). The
//   isolated reproduction configuration is `docker --network none`
//   (loopback-only netns, separately reported); host-networking runs are
//   explicitly limited to the tripwire + browser defense above, and neither
//   claims a closed world nor self-proves the environment's safety.
// - No credentials are committed and no log/error message prints URL userinfo
//   or raw query strings: logged URLs are reduced to pathname + minimal ids
//   via `safePath()`, and refusal messages never echo a caller-supplied URL.
//
// Intentional scope exclusions (documented, not weakened):
// - `regHeadingDup` / `workHeadingDup` heading counts are recorded into the
//   JSON log only. The duplicate lives in the app shell, out of scope here.
// - Seal-inspection steps needing a sealed revision are excluded (see above).
// - Viewport gating is width-based, matching `isMobileViewport` (< 1024):
//   the desktop test runs where the viewport is >= 1024 wide (desktop-1024 and
//   desktop-1440 projects); the mobile test runs where it is < 1024 wide
//   (mobile-390 and tablet-768 projects). Skips for other widths are
//   deliberate scope boundaries, not passes.

const syntheticOptIn = process.env.KSI_OWNER_JOURNEY_SYNTHETIC === "1";
// Presence-based: ANY caller-supplied value — including an empty string —
// counts as externally configured and is refused. (An empty string is not a
// usable base and must not silently fall through to a run.)
const externalBaseConfigured = "KSI_DASHBOARD_E2E_BASE_URL" in process.env;

test.skip(
  externalBaseConfigured,
  "Test bodies are excluded for any caller-supplied base URL; the selected config may still start its webServer.",
);
test.skip(
  !syntheticOptIn,
  "Synthetic opt-in is absent; the diagnostic is also disabled until an isolated runner exists.",
);
test.skip(
  true,
  "Owner-journey mutation is disabled until a verified task-owned network-isolated runner exists.",
);

/** Reduce a URL to its pathname for logs; never emits userinfo, host, or query. */
function safePath(raw: string): string {
  try {
    return new URL(raw, "http://localhost").pathname;
  } catch {
    return "(unparsable-url)";
  }
}

/** Deterministic synthetic upload bytes. Not a real GeoTIFF, not customer data. */
function syntheticOrthoFile(): { name: string; mimeType: string; buffer: Buffer } {
  const magic = Buffer.from([0x49, 0x49, 0x2a, 0x00, 0x08, 0x00, 0x00, 0x00]);
  const marker = Buffer.from(
    "KSI-SYNTHETIC-OWNER-JOURNEY-PROBE/ortho: deterministic synthetic bytes for a portable fixture-only test. Not a field capture, not customer data.",
    "utf8",
  );
  return {
    name: "synthetic-owner-journey-ortho.tif",
    mimeType: "application/octet-stream",
    buffer: Buffer.concat([magic, marker]),
  };
}

const axePath = join(process.cwd(), "node_modules", "axe-core", "axe.min.js");

// In-browser loopback guard: defense-in-depth only (see Network header).
// Installed on the context (not the page), so targeted page-level `unroute`
// calls below cannot lift it. The loopback-only tripwire runs FIRST via
// `requireLoopbackOnlyInterfaces()` — where even loopback-only addresses are
// not observed, the run aborts before any navigation or mutation. Passing
// that tripwire proves no isolation; actual reproduction belongs in a
// network-isolated task-owned container.
test.beforeEach(async ({ context }) => {
  requireLoopbackOnlyInterfaces();
  await context.route(/^https?:\/\//, (route) => {
    if (isLoopbackHostname(new URL(route.request().url()).hostname)) {
      return route.continue();
    }
    return route.abort("blockedbyclient");
  });
});

function isMobileViewport(page: Page): boolean {
  return (page.viewportSize()?.width ?? 0) < 1024;
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: /개발 Operations Console 시작/ }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(name);
  await page.screenshot({ path, fullPage: false });
  await testInfo.attach(name, { path, contentType: "image/png" });
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
}

async function seriousAxeViolations(page: Page) {
  await page.addScriptTag({ path: axePath });
  return page.evaluate(async () => {
    const result = await (window as unknown as { axe: { run: () => Promise<{ violations: Array<{ id: string; impact: string | null }> }> } }).axe.run();
    return result.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  });
}

/**
 * Guard self-check: a reserved non-loopback URL must be aborted by the
 * context guard before any packet (BLOCKED_BY_CLIENT). Runs before any
 * same-origin navigation in each test. Fails closed on any other outcome.
 */
async function expectNonLoopbackBlocked(page: Page) {
  const outcome = await page
    .goto("http://example.invalid/", { timeout: 10_000 })
    .then(() => "(unexpected-success)", (error: unknown) => String(error));
  expect(outcome).toMatch(/BLOCKED_BY_CLIENT/i);
}

/**
 * Read-only fixture-identity proof. Must pass BEFORE any mutation: the seeded
 * synthetic site and the seeded synthetic external work order must both be
 * visible. Any non-fixture service fails here and the test aborts before any
 * POST/seal.
 */
async function expectSyntheticFixtureIdentity(page: Page) {
  await page.goto("/field/new");
  await expect(page.getByRole("link", { name: /E2E 현장 작업공간/ })).toBeVisible();
  await page.goto("/field");
  await expect(page.getByRole("link", { name: /E2E 외부 산출물 등록/ }).first()).toBeVisible();
}

test("owner probe: desktop registration creates a work order and submits a synthetic revision", async ({ page }, testInfo) => {
  test.skip(isMobileViewport(page), "desktop-only flow");
  test.setTimeout(240_000);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  const apiCalls: string[] = [];
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/api/observation-work-orders/") || url.includes("/api/sites/")) {
      apiCalls.push(`${response.status()} ${response.request().method()} ${safePath(url)}`);
    }
  });

  await expectNonLoopbackBlocked(page);
  await login(page);
  await expectSyntheticFixtureIdentity(page);

  // 1. 현장 선택 → 관측 자료 등록 첫 화면 (초기 무자료 상태)
  await page.goto("/field/new");
  await page.getByRole("link", { name: /E2E 현장 작업공간/ }).click();
  await expect(page).toHaveURL(/\/sites\/e2e-site-workspace\/observations\/new$/);
  await expect(page.getByRole("heading", { name: "관측 자료 등록", exact: true, level: 2 })).toBeVisible();
  // 앱 셸 sr-only h1과 본문 h2의 동일 문구 중복 여부 — 셸 영역이라 수정은 범위 밖, 증거만 기록한다.
  const regHeadingDup = await page.getByRole("heading", { name: "관측 자료 등록", exact: true }).count();
  void regHeadingDup;
  await expect(page.getByRole("list", { name: "자료 등록 흐름" })).toBeVisible();
  const submit = page.getByRole("button", { name: "관측 자료 등록 계속", exact: true });
  await expect(submit).toBeDisabled();
  await expectNoHorizontalOverflow(page);
  expect(await seriousAxeViolations(page)).toEqual([]);
  await shot(page, testInfo, "before-01-reg-empty-1440.png");

  // 2. 단일 활성 구역은 미리 골라진다 (범위 확인 후 제출 가능)
  // 범위 공지는 작은 화면 요약과 데스크톱 폼에 하나씩 있어 role=status 쪽으로 좁힌다.
  await expect(page.getByRole("status").filter({ hasText: "선택한 구역에서 시작합니다." })).toBeVisible();
  await page.getByRole("textbox", { name: "작업 이름", exact: true }).click();
  await page.keyboard.type("프로브 1차 관측");
  await expect(submit).toBeEnabled();
  // 단일 구역 선택 시 돌아가기 링크가 승인 범위를 싣는다.
  await expect(page.getByRole("link", { name: "현장으로 돌아가기" })).toHaveAttribute("href", /workAreaId=/);
  // 키보드 해제 → 필수 안내 + 제출 잠금, 다시 선택 → 복구
  await page.keyboard.press("Tab");
  await page.keyboard.press("Space");
  await expect(submit).toBeDisabled();
  await expect(page.getByText("비교할 작업구역을 하나 이상 선택하세요.")).toBeVisible();
  await page.keyboard.press("Space");
  await expect(submit).toBeEnabled();
  await shot(page, testInfo, "before-02-reg-filled-1440.png");

  // 3. 실제 생성 POST → 작업 상세 #external-submissions
  await submit.click();
  await expect(page).toHaveURL(/\/field\/work-orders\/.+#external-submissions/, { timeout: 30_000 });
  const workOrderPath = safePath(page.url());
  const workOrderId = workOrderPath.split("/field/work-orders/")[1]!.split("#")[0]!;
  await expect(page.getByRole("heading", { name: "관측 자료와 검사 확인", level: 2 })).toBeVisible();
  // 동일 문구 제목 중복 여부 — 증거만 기록한다.
  const workHeadingDup = await page.getByRole("heading", { name: "관측 자료와 검사 확인", exact: true }).count();
  void workHeadingDup;
  const stageSection = page.getByRole("heading", { name: "플랫폼 작업 상태" }).locator("..").locator("..");
  const stageText = (await stageSection.innerText()).replace(/\s+/g, " ").trim();
  // 상태 배너의 다음 행동은 화면 내 실제 기록으로 이어진다(데드 앵커 회귀 방지).
  await expect(stageSection.getByRole("link", { name: "자료 등록·검사 기록으로 이동" })).toHaveAttribute("href", "#external-submissions");
  await expect(page.getByText("아직 등록된 관측 자료가 없습니다.")).toBeVisible();
  // 유지된 제출이 없으면 새 등록 폼이 펼침 상태로 바로 보인다(summary가 아닌 입력 자체로 확인).
  await expect(page.getByRole("textbox", { name: "재구성 소프트웨어 이름" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(await seriousAxeViolations(page)).toEqual([]);
  await shot(page, testInfo, "before-03-work-new-1440.png");

  // 4. V3 신고 입력 + 합성 바이트 선택 → 봉인 시도 (fixture capability 경계)
  //
  // 이 스택에는 evidence storage(S3) 구성이 없으므로 봉인이 성공할 수
  // 없다. 무엇이 일어나는지는 추론하지 않고 실행으로 확인한다: BFF 상태와
  // 사용자 대면 결과를 있는 그대로 기록하고, 성공 표시는 절대 허용하지
  // 않는다. 이전 실행의 uncaught 500 관찰은 폐기한다 — 미구성 저장소 실패
  // 경로는 다른 담당자의 genuine fail-closed 수정(`STORAGE_UNAVAILABLE`
  // HTTP 503, 외래 범위 404 유지, 저널 무기록)이 worktree에 반영되었고,
  // 이 실행이 그 수정 이후의 재검증이다. S3-backed 성공 경로는
  // UNAVAILABLE이며 여기서 주장하지 않는다. 업로드 입력은 합성 더미
  // 바이트(syntheticOrthoFile)이며 실제 GeoTIFF가 아니다.
  await page.getByRole("textbox", { name: "재구성 소프트웨어 이름" }).fill("e2e-probe-mosaic");
  await page.getByRole("textbox", { name: "재구성 소프트웨어 버전" }).fill("0.0.1-probe");
  // datetime-local 입력은 초 없이 채운다: 이 headless Chromium은 set 시 ":ss"를
  // 살균하고(Playwright "Malformed value"), 제품 파서(seoulDateTimeLocalToUtc)는
  // "YYYY-MM-DDTHH:mm"과 "YYYY-MM-DDTHH:mm:00"을 동일 instants로 취급한다.
  await page.getByLabel("촬영 시작 시각 (한국 표준시)").fill("2026-10-20T10:00");
  await page.getByLabel("촬영 종료 시각 (한국 표준시)").fill("2026-10-20T10:15");
  await page.getByLabel("정사영상 GeoTIFF").setInputFiles(syntheticOrthoFile());
  await expect(page.getByText("확인 완료")).toBeVisible({ timeout: 30_000 });
  const finish = page.getByRole("button", { name: "자료 등록 마치기" });
  await expect(finish).toBeEnabled();
  await shot(page, testInfo, "before-04-ready-to-submit-1440.png");
  await finish.click();
  await expect(page.getByText("응답을 확인하지 못했습니다.")).toBeVisible({ timeout: 60_000 });
  // 불확실 뒤에 성공을 주장하지 않는다 — 조용한 성공이 가장 나쁜 거짓말이다.
  await expect(page.getByText("파일 등록을 확인했습니다.")).toHaveCount(0);
  await shot(page, testInfo, "before-05-after-seal-1440.png");

  // 5. fail-closed 상태 확인: 봉인 불확실 뒤에도 등록된 자료가 있다고 주장하지 않는다.
  await expect(page.getByText("아직 등록된 관측 자료가 없습니다.")).toBeVisible();
  const submissionsText = (await page.locator("#external-submissions").innerText()).replace(/\s+/g, " ").slice(0, 1200);
  await expectNoHorizontalOverflow(page);
  expect(await seriousAxeViolations(page)).toEqual([]);
  await shot(page, testInfo, "before-06-submissions-1440.png");

  // 6. 통제된 목록 실패: 목록 GET 중단 → 오류 상태 + 복구 (합성 장애 주입).
  // 컨텍스트 루프백 가드는 유지한 채 이 단계의 page-레벨 중단만 targeted unroute로 해제한다.
  const listPath = `/api/observation-work-orders/${workOrderId}/external-reconstruction-submissions`;
  const listPredicate = (url: URL) => url.pathname === listPath;
  const abortList = (route: Route) => route.abort();
  await page.route(listPredicate, abortList);
  await page.reload();
  await expect(page.getByText("등록 목록을 불러오지 못했습니다.")).toBeVisible({ timeout: 30_000 });
  await shot(page, testInfo, "before-07-list-failure-1440.png");
  await page.unroute(listPredicate, abortList);
  await page.getByRole("button", { name: "목록 다시 시도" }).click();
  await expect(page.getByText("등록 목록을 불러오지 못했습니다.")).not.toBeVisible({ timeout: 30_000 });
  await shot(page, testInfo, "before-08-list-recovered-1440.png");

  // 7. 불명 검사 응답 주입은 sealed revision이 있어야 하며, 기본 fixture에는
  // 없다(봉인이 storage 부재로 uncertain). S3-backed 모드는 unverified이므로
  // 실행하지 않고 범위 제외를 로그에 명시한다.
  apiCalls.push("SCOPE-EXCLUDED inspection-unknown: no sealed revision without evidence storage (S3); S3-backed mode unavailable, not claimed");

  expect(pageErrors).toEqual([]);
  const logPath = testInfo.outputPath("desktop-journey-log.json");
  const { writeFileSync } = await import("node:fs");
  writeFileSync(
    logPath,
    JSON.stringify({ runId: process.env.OJ_RUN_ID ?? "(none)", workOrderPath, stageText, submissionsText: submissionsText.slice(0, 600), apiCalls, regHeadingDup, workHeadingDup }, null, 2),
  );
  await testInfo.attach("desktop-journey-log", { path: logPath, contentType: "application/json" });
});

test("owner probe: mobile keeps the seeded external order read-only", async ({ page }, testInfo) => {
  test.skip(!isMobileViewport(page), "mobile-only flow");
  test.setTimeout(180_000);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await expectNonLoopbackBlocked(page);
  await login(page);
  await expectSyntheticFixtureIdentity(page);

  // 등록 진입: 쓰기 폼 숨김 + 읽기 범위 요약
  await page.goto("/field/new");
  await page.getByRole("link", { name: /E2E 현장 작업공간/ }).click();
  await expect(page.getByRole("heading", { name: "관측 자료 등록", exact: true, level: 2 })).toBeVisible();
  // 앱 셸 sr-only h1과 본문 h2의 동일 문구 중복 여부 — 셸 영역이라 수정은 범위 밖, 증거만 기록한다.
  const regHeadingDup = await page.getByRole("heading", { name: "관측 자료 등록", exact: true }).count();
  void regHeadingDup;
  await expect(page.getByText("이 화면의 등록 범위")).toBeVisible();
  await expect(page.getByRole("button", { name: "관측 자료 등록 계속", exact: true })).not.toBeVisible();
  await expect(page.getByText("노트북에서 같은 계정으로")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(await seriousAxeViolations(page)).toEqual([]);
  await shot(page, testInfo, "before-10-mobile-new-390.png");

  // 작업 상세: 읽기 전용 — 검사 새로고침은 가능, 파일 선택·이어하기는 불가
  await page.goto("/field");
  await page.getByRole("link", { name: /E2E 외부 산출물 등록/ }).first().click();
  await expect(page).toHaveURL(/\/field\/work-orders\//);
  await expect(page.getByRole("heading", { name: "관측 자료와 검사 확인", level: 2 })).toBeVisible();
  // 동일 문구 제목 중복 여부 — 증거만 기록한다.
  const workHeadingDup = await page.getByRole("heading", { name: "관측 자료와 검사 확인", exact: true }).count();
  void workHeadingDup;
  await expect(page.getByText("노트북에서 같은 계정으로")).toBeVisible();
  await expect(page.getByLabel("정사영상 GeoTIFF")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "자료 등록 마치기" })).not.toBeVisible();
  // 빈 펼침 제거: 쓰기 경계가 새 등록 펼침 자체를 숨기므로 펼침만 남아 열어도
  // 비어 보이는 상태가 없다. 안내는 상단의 노트북 계속 안내가 맡는다.
  await expect(page.getByText("새 산출물 등록", { exact: true })).not.toBeVisible();
  await expectNoHorizontalOverflow(page);
  expect(await seriousAxeViolations(page)).toEqual([]);
  await shot(page, testInfo, "before-11-mobile-work-390.png");

  // 키보드 종단: 숨겨진 쓰기 컨트롤에 포커스가 닿지 않는다.
  const focused: string[] = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Tab");
    const label = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement | null;
      if (!active) return "(none)";
      const visible = active.getClientRects().length > 0;
      return `${active.tagName}:${(active.getAttribute("aria-label") ?? active.textContent ?? "").trim().slice(0, 24)}:${visible ? "visible" : "HIDDEN"}`;
    });
    focused.push(label);
    if (label.startsWith("BODY")) break;
  }
  const hiddenFocus = focused.filter((entry) => entry.endsWith(":HIDDEN"));
  expect(hiddenFocus).toEqual([]);
  const tabPath = testInfo.outputPath("mobile-tab-order.json");
  const { writeFileSync } = await import("node:fs");
  writeFileSync(tabPath, JSON.stringify({ focused, regHeadingDup }, null, 2));
  await testInfo.attach("mobile-tab-order", { path: tabPath, contentType: "application/json" });
  expect(pageErrors).toEqual([]);
});
