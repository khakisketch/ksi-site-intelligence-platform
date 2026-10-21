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

async function openPhoneFilters(page: Page) {
  const toggle = page.getByText("필터·정렬", { exact: true }).filter({ visible: true });
  if (!await toggle.evaluate((node) => node.closest("details")?.open)) await toggle.tap();
  return toggle;
}

async function selectSort(page: Page, value: string, phone: boolean) {
  if (phone) await openPhoneFilters(page);
  const sort = page.getByRole("combobox", { name: "정렬 기준" });
  await sort.focus();
  await sort.selectOption(value);
  if (phone) await page.getByRole("button", { name: "적용", exact: true }).click();
}

async function expectSort(page: Page, value: string, phone: boolean) {
  const toggle = phone ? await openPhoneFilters(page) : null;
  await expect(page.getByRole("combobox", { name: "정렬 기준" })).toHaveValue(value);
  if (toggle) await toggle.tap();
}

test.beforeEach(async ({ page }) => {
  await login(page);
});

test("폭에 맞춰 검색·정렬과 장식의 우선순위를 바꾼다", async ({ page }, testInfo) => {
  const phone = testInfo.project.name === "mobile-390";
  await page.goto("/sites");
  const main = page.getByRole("main");
  const search = main.getByRole("searchbox", { name: "현장 찾기" });
  const sort = main.getByRole("combobox", { name: "정렬 기준" });
  await expect(search).toBeVisible();
  if (phone) await expect(sort).toBeHidden();
  else await expect(sort).toBeVisible();
  await expect(search).toHaveAttribute("placeholder", "현장명 또는 ID");
  await expect(main.getByRole("button", { name: "검색", exact: true })).toHaveCount(0);
  const searchBox = await search.boundingBox();
  expect(searchBox!.height).toBeGreaterThanOrEqual(testInfo.project.name.startsWith("desktop") ? 36 : 44);
  if (phone) {
    expect(searchBox!.width).toBeGreaterThanOrEqual(350);
    await expect(page.getByText("상태 필터", { exact: true })).toBeHidden();
    await openPhoneFilters(page);
    await expect(sort).toBeVisible();
    await expect(page.getByRole("combobox", { name: "현장 상태" })).toBeVisible();
    await page.getByText("필터·정렬", { exact: true }).filter({ visible: true }).click();
  } else {
    const sortBox = await sort.boundingBox();
    expect(searchBox!.height).toBe(sortBox!.height);
    expect(searchBox!.y).toBe(sortBox!.y);
  }
  await firstSiteId(page);
  const desktop = testInfo.project.name.startsWith("desktop");
  if (desktop) {
    // 기본값은 실제 미리보기 비주얼 카드다 — 각 카드에 미리보기 영역이 있다.
    await expect(main.locator("[data-site-card]:visible").first()).toBeVisible();
    await expect(main.locator("[data-site-card]:visible").first().locator("[data-site-preview]")).toBeAttached();
    await expect(main.getByRole("link", { name: "현장 열기", exact: true }).first()).toBeVisible();
  } else {
    await expect(page.getByRole("region", { name: "현장 목록" })).toBeVisible();
    await expect(page.getByRole("link", { name: "현장 열기", exact: true }).first()).toBeVisible();
  }
  // 장식 표지·기본 이미지 문구가 없다 — 카드의 전부는 식별 정보와 다음 행동이다.
  await expect(main.getByText("기본 표지", { exact: true })).toHaveCount(0);
  await expect(main.getByText("기본 이미지", { exact: true })).toHaveCount(0);
  await expect(main.locator("[data-site-cover]")).toHaveCount(0);
  if (phone) {
    const open = page.getByRole("link", { name: "현장 열기", exact: true }).first();
    const actionBox = await open.boundingBox();
    const cardBox = await open.locator("xpath=ancestor::li[1]").boundingBox();
    expect(actionBox!.width).toBeGreaterThanOrEqual(cardBox!.width - 32);
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
});

test("입력과 즉시 정렬이 겹쳐도 최신 검색어와 필터를 잃지 않는다", async ({ page }, testInfo) => {
  const phone = testInfo.project.name === "mobile-390";
  await page.goto("/sites");
  const id = await firstSiteId(page);
  await page.goto("/sites?group=attention");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  const sort = page.getByRole("combobox", { name: "정렬 기준" });
  await search.fill(id);
  await selectSort(page, "name", phone);
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(id);
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("name");
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
  await expect(search).toHaveValue(id);
  if (phone) {
    await expect(sort).toBeHidden();
    await expect.poll(() => page.getByText("필터·정렬", { exact: true }).filter({ visible: true }).evaluate((node) => node.closest("summary") === document.activeElement)).toBe(true);
  } else {
    await expect(sort).toHaveValue("name");
    await expect(sort).toBeFocused();
  }
  if (!testInfo.project.name.startsWith("desktop")) {
    const formBox = await search.locator("xpath=ancestor::form[1]").boundingBox();
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

test("Enter 검색과 정렬의 뒤로가기는 표시 값과 결과 조건을 복원한다", async ({ page }, testInfo) => {
  const phone = testInfo.project.name === "mobile-390";
  await page.goto("/sites");
  const id = await firstSiteId(page);
  await page.goto("/sites?group=attention");
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  await search.fill(id);
  await search.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(id);
  await selectSort(page, "name", phone);
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("name");
  await page.goBack();
  await expect(search).toHaveValue(id);
  await expectSort(page, "attention", phone);
  await page.goBack();
  await expect(search).toHaveValue("");
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
  await page.goForward();
  await expect(search).toHaveValue(id);
});

test("한글 조합 중에는 검색하지 않고 빈 결과에서도 입력과 초기화를 유지한다", async ({ page }, testInfo) => {
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
  await expectSort(page, "attention", testInfo.project.name === "mobile-390");
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
  // Zero-count groups render no chip (attention is 0 in the isolated fixture):
  // race the slow response against a chip that actually exists in this ledger.
  const chip = page.getByRole("group", { name: "현장 상태 필터" }).getByRole("link", { name: /등록됨|준비 중|순찰 가능|확인 필요|운영 중단/ }).first();
  const chipGroup = new URL((await chip.getAttribute("href"))!, page.url()).searchParams.get("group")!;
  await page.route((url) => url.pathname === "/sites" && url.searchParams.get("group") === chipGroup, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700)); // Deliberately slower than the search debounce.
    await route.continue();
  });
  await search.fill(id);
  await chip.click();
  await expect.poll(() => new URL(page.url()).searchParams.get("group")).toBe(chipGroup);
  await page.waitForTimeout(450);
  expect(new URL(page.url()).searchParams.get("group")).toBe(chipGroup);
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

test("찾은 현장을 열었다 돌아와도 검색과 정렬 조건이 남는다", async ({ page }, testInfo) => {
  await page.goto("/sites");
  const id = await firstSiteId(page);
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  await search.fill(id);
  await search.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(id);
  await selectSort(page, "name", testInfo.project.name === "mobile-390");
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("name");
  const open = page.getByRole("link", { name: "현장 열기", exact: true });
  await expect(open).toHaveAttribute("href", `/sites/${encodeURIComponent(id)}`);
  await open.click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(`/sites/${encodeURIComponent(id)}`);
  await page.goBack();
  await expect(search).toHaveValue(id);
  await expectSort(page, "name", testInfo.project.name === "mobile-390");
  expect(new URL(page.url()).searchParams.get("q")).toBe(id);
});

test("휴대폰 필터는 선택만으로 적용되지 않고 최신 검색 초안과 함께 적용된다", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-390", "640px 이상은 기존 바로 정렬 표면을 유지합니다.");
  await page.goto("/sites");
  const id = await firstSiteId(page);
  await page.goto(`/sites?group=attention&sort=updated&q=${encodeURIComponent(id)}`);
  const search = page.getByRole("searchbox", { name: "현장 찾기" });
  const toggle = await openPhoneFilters(page);
  const sort = page.getByRole("combobox", { name: "정렬 기준" });
  const group = page.getByRole("combobox", { name: "현장 상태" });
  await sort.selectOption("name");
  await group.selectOption("all");
  await page.waitForTimeout(400);
  expect(new URL(page.url()).searchParams.get("sort")).toBe("updated");
  expect(new URL(page.url()).searchParams.get("group")).toBe("attention");
  await toggle.tap();
  await openPhoneFilters(page);
  await expect(sort).toHaveValue("updated");
  await expect(group).toHaveValue("attention");

  await sort.selectOption("name");
  await group.selectOption("all");
  const draft = id.slice(0, -1);
  await search.fill(draft);
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(draft);
  await expect(sort).toHaveValue("name");
  await expect(group).toHaveValue("all");
  await page.getByRole("button", { name: "적용", exact: true }).tap();
  await expect.poll(() => new URL(page.url()).searchParams.get("sort")).toBe("name");
  expect(new URL(page.url()).searchParams.has("group")).toBe(false);
  expect(new URL(page.url()).searchParams.get("q")).toBe(draft);
  await expect(sort).toBeHidden();
  await expect.poll(() => toggle.evaluate((node) => node.closest("summary") === document.activeElement)).toBe(true);
  await openPhoneFilters(page);
  await page.getByRole("link", { name: "초기화", exact: true }).tap();
  await expect(page).toHaveURL(/\/sites$/);
  await expect(search).toHaveValue("");
  await expect(sort).toBeHidden();
  await search.fill("아직 적용되지 않은 초안");
  await openPhoneFilters(page);
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
  await page.getByRole("link", { name: "초기화", exact: true }).tap();
  await expect(search).toHaveValue("");
  await page.waitForTimeout(450);
  expect(new URL(page.url()).searchParams.has("q")).toBe(false);
});
