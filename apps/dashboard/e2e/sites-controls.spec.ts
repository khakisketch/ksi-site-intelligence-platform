import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "개발 Operations Console 시작" }).click();
  await expect(page).toHaveURL(/\/$/);
}

async function firstSiteId(page: Page) {
  const first = page.locator('main a[href^="/sites/"]:not([href="/sites/new"]):visible').first();
  await expect(first).toBeVisible();
  const href = await first.getAttribute("href");
  return decodeURIComponent(new URL(href!, "http://localhost").pathname.split("/")[2]);
}

test.beforeEach(async ({ page }) => {
  await login(page);
});

test("검색·정렬은 버튼 없는 일관된 조작부이며 카드와 표에 기본 표시를 둔다", async ({ page }, testInfo) => {
  await page.goto("/sites");
  const main = page.getByRole("main");
  const search = main.getByRole("searchbox", { name: "현장 찾기" });
  const sort = main.getByRole("combobox", { name: "정렬 기준" });
  await expect(search).toBeVisible();
  await expect(sort).toBeVisible();
  await expect(search).toHaveAttribute("placeholder", "현장명 또는 ID");
  await expect(main.getByRole("button", { name: "검색", exact: true })).toHaveCount(0);
  const searchBox = await search.boundingBox();
  const sortBox = await sort.boundingBox();
  expect(searchBox!.height).toBe(sortBox!.height);
  expect(searchBox!.height).toBeGreaterThanOrEqual(testInfo.project.name.startsWith("desktop") ? 36 : 44);
  expect(searchBox!.y).toBe(sortBox!.y);
  await firstSiteId(page);
  await expect(main.getByText("기본 이미지", { exact: true }).first()).toBeAttached();
  expect(await main.getByText("기본 이미지", { exact: true }).evaluateAll((nodes) => nodes.some((n) => n.getBoundingClientRect().width > 0))).toBe(true);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});

test("입력과 즉시 정렬이 겹쳐도 최신 검색어와 필터를 잃지 않는다", async ({ page }, testInfo) => {
  await page.goto("/sites");
  const id = await firstSiteId(page);
  await page.goto("/sites?group=attention");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  const sort = page.getByRole("combobox", { name: "정렬 기준" });
  await search.fill(id);
  await sort.focus();
  await sort.selectOption("name");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(id);
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("name");
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
  await expect(search).toHaveValue(id);
  await expect(sort).toHaveValue("name");
  await expect(sort).toBeFocused();
  if (!testInfo.project.name.startsWith("desktop")) {
    const formBox = await page.getByRole("search", { name: "현장 검색과 정렬" }).boundingBox();
    const inputBox = await search.boundingBox();
    const clearBox = await page.getByRole("button", { name: "검색어 지우기", exact: true }).boundingBox();
    expect(formBox!.height).toBe(inputBox!.height); // No extra reset-button row when filters become active.
    expect(clearBox!.height).toBeGreaterThanOrEqual(44);
    expect(clearBox!.width).toBeGreaterThanOrEqual(44);
  }
  await search.fill("");
  await expect.poll(() => new URL(page.url()).searchParams.has("q")).toBe(false);
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
  expect(new URL(page.url()).searchParams.get("sort")).toBe("name");
});

test("Enter 검색과 정렬의 뒤로가기는 표시 값과 결과 조건을 복원한다", async ({ page }) => {
  await page.goto("/sites");
  const id = await firstSiteId(page);
  await page.goto("/sites?group=attention");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  const sort = page.getByRole("combobox", { name: "정렬 기준" });
  await search.fill(id);
  await search.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(id);
  await sort.selectOption("name");
  await expect(sort).toHaveValue("name");
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("name");
  await page.goBack();
  await expect(search).toHaveValue(id);
  await expect(sort).toHaveValue("attention");
  await page.goBack();
  await expect(search).toHaveValue("");
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
  await page.goForward();
  await expect(search).toHaveValue(id);
});

test("한글 조합 중에는 검색하지 않고 빈 결과에서도 입력과 초기화를 유지한다", async ({ page }) => {
  await page.goto("/sites?group=attention&sort=updated");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  await search.dispatchEvent("compositionstart");
  await search.fill("검색 검증용 없는 현장");
  await search.press("Enter");
  await page.waitForTimeout(450); // Deliberately exceeds the debounce; IME composition must not navigate.
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
  await search.dispatchEvent("compositionend");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("검색 검증용 없는 현장");
  await expect(page.getByText("조건에 맞는 현장이 없습니다", { exact: true })).toBeVisible();
  await expect(search).toBeEnabled();
  await page.getByRole("link", { name: "필터 초기화", exact: true }).click();
  await expect(page).toHaveURL(/\/sites$/);
  await expect(search).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "정렬 기준" })).toHaveValue("attention");
});

test("검색칸에 포커스가 있어도 q만 바뀌는 뒤로가기는 초안과 타이머를 되돌린다", async ({ page }) => {
  await page.goto("/sites");
  const id = await firstSiteId(page);
  await page.goto("/sites?group=attention");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  await search.fill(id);
  await search.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(id);
  await search.fill("두 번째 없는 현장");
  await search.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("두 번째 없는 현장");
  await page.goBack();
  await expect(search).toHaveValue(id);
  await search.fill("뒤로가기 전에 입력한 초안");
  await page.goBack();
  await expect(search).toHaveValue("");
  await page.waitForTimeout(450); // A superseded debounce must not undo history navigation.
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
});

test("느린 필터 응답 중 이전 검색 타이머가 선택한 묶음을 덮지 않는다", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "서버 링크 상태 칩은 desktop 전용입니다.");
  await page.goto("/sites");
  const id = await firstSiteId(page);
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  await page.route((url) => url.pathname === "/sites" && url.searchParams.get("group") === "attention", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700)); // Deliberately slower than the search debounce.
    await route.continue();
  });
  await search.fill(id);
  await page.getByRole("group", { name: "현장 상태 필터" }).getByRole("link", { name: /확인 필요/ }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("group")).toBe("attention");
  await page.waitForTimeout(450);
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
  await expect(search).toHaveValue("");
});

test("빈 결과의 초기화도 아직 적용되지 않은 검색을 취소한다", async ({ page }) => {
  await page.goto("/sites?q=처음부터 없는 현장");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  await expect(page.getByText("조건에 맞는 현장이 없습니다", { exact: true })).toBeVisible();
  await page.route((url) => url.pathname === "/sites" && !url.searchParams.has("q"), async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700));
    await route.continue();
  });
  await search.fill("초기화 전에 입력한 초안");
  await page.getByRole("link", { name: "필터 초기화", exact: true }).click();
  await expect(page).toHaveURL(/\/sites$/);
  await expect(search).toHaveValue("");
  await page.waitForTimeout(450);
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
});

test("찾은 현장을 열었다 돌아와도 검색과 정렬 조건이 남는다", async ({ page }) => {
  await page.goto("/sites");
  const id = await firstSiteId(page);
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  await search.fill(id);
  await search.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(id);
  await page.getByRole("combobox", { name: "정렬 기준" }).selectOption("name");
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("name");
  const open = page.getByRole("link", { name: "현장 열기", exact: true });
  await expect(open).toHaveAttribute("href", `/sites/${encodeURIComponent(id)}`);
  await open.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(`/sites/${encodeURIComponent(id)}`);
  await page.goBack();
  await expect(search).toHaveValue(id);
  await expect(page.getByRole("combobox", { name: "정렬 기준" })).toHaveValue("name");
  expect(new URL(page.url()).searchParams.get("q")).toBe(id);
});
