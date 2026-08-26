import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("keeps the selected home and switches only the remaining-site presentation", async ({ page }) => {
  await expect(page.getByTestId("home-candidates")).toBeVisible();
  await expect(page.getByTestId("candidate-home-a")).toBeVisible();
  await expect(page.getByRole("heading", { name: "전체 4곳 · 확인 필요 2곳" })).toBeVisible();
  await expect(page.getByRole("banner", { name: "다른 현장 표현 후보" })).toContainText("개별 목록형");
  await expect(page.getByTestId("candidate-remaining-a")).toBeVisible();

  await page.getByRole("button", { name: "B", exact: true }).click();
  await expect(page.getByTestId("candidate-home-a")).toBeVisible();
  await expect(page.getByRole("heading", { name: "확인이 필요한 현장" })).toBeVisible();
  await expect(page.getByTestId("candidate-remaining-b")).toBeVisible();
  await expect(page.getByRole("banner", { name: "다른 현장 표현 후보" })).toContainText("최근 업데이트형");

  await page.getByRole("button", { name: "C", exact: true }).click();
  await expect(page.getByTestId("candidate-home-a")).toBeVisible();
  await expect(page.getByTestId("candidate-remaining-c")).toBeVisible();
  await expect(page.getByRole("banner", { name: "다른 현장 표현 후보" })).toContainText("요약형");
});

test("list variant separates two attention cases from observation-dated other sites", async ({ page }) => {
  const siteList = page.getByTestId("candidate-remaining-a");
  await expect(siteList).toBeVisible();
  await expect(siteList.getByRole("heading", { name: "다른 현장" })).toBeVisible();
  await expect(siteList.getByRole("button", { name: /서초 복합물류센터/ })).toHaveCount(0);
  await expect(siteList.getByRole("button", { name: /김포 제조공장/ })).toHaveCount(0);
  await expect(siteList.getByRole("button", { name: /인천 자재야적장, 8월 20일 09:36 관측, 결과 준비/ })).toBeVisible();
  await expect(siteList.getByRole("button", { name: /판교 데이터센터, 8월 19일 14:05 관측, 새 안건 없음/ })).toBeVisible();

  await siteList.getByRole("button", { name: "전체 보기" }).click();
  await expect(page.getByTestId("candidate-sites")).toBeVisible();
});

test("recent-update cards are curated, grounded, and open the correct site context", async ({ page }) => {
  await page.getByRole("button", { name: "B", exact: true }).click();
  const cards = page.getByTestId("candidate-remaining-b");
  await expect(cards.getByRole("heading", { name: "최근 업데이트" })).toBeVisible();
  await expect(cards.getByRole("img", { name: "합성 데이터로 만든 인천 자재야적장 항공 관측 이미지" })).toHaveJSProperty("complete", true);
  await expect(cards.getByRole("img", { name: "합성 데이터로 만든 판교 데이터센터 공사 현장 항공 관측 이미지" })).toHaveJSProperty("complete", true);
  await expect(cards.getByText("상대 체적 비교 결과 준비")).toBeVisible();
  await expect(cards.getByText("새 확인 안건 없음")).toBeVisible();
  await expect(cards.getByText(/장비 연결|동기화|처리 시작|어댑터/)).toHaveCount(0);

  await cards.getByRole("button", { name: /인천 자재야적장, 새 결과, 상대 체적 비교 결과 준비/ }).click();
  await expect(page.getByRole("heading", { name: "인천 자재야적장" })).toBeVisible();
  await expect(page.getByText(/절대 물량으로 확정하지 않습니다/)).toBeVisible();
  const siteDetailButton = page.getByRole("button", { name: "현장 화면에서 보기" });
  await expect(siteDetailButton).toBeInViewport();
  await expect(siteDetailButton).toHaveCSS("background-color", "rgb(23, 24, 22)");
  await expect.poll(() => siteDetailButton.evaluate((button) => {
    const rect = button.getBoundingClientRect();
    const topElement = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return topElement === button || button.contains(topElement);
  })).toBe(true);
  await page.keyboard.press("Escape");

  await cards.getByRole("button", { name: /판교 데이터센터, 최근 관측, 새 확인 안건 없음/ }).click();
  await expect(page.getByRole("heading", { name: "판교 데이터센터" })).toBeVisible();
  await expect(page.getByText(/현장 전체의 정상이나 안전을 의미하지 않습니다/)).toBeVisible();
  await page.getByRole("button", { name: "현장 화면에서 보기" }).click();
  await expect(page.getByTestId("candidate-sites")).toBeVisible();
});

test("summary variant remains available beside the recent-update option", async ({ page }) => {
  await page.getByRole("button", { name: "C", exact: true }).click();
  const summary = page.getByTestId("candidate-remaining-c");
  await expect(summary.getByText("지금 우선 확인할 안건이 없습니다.")).toBeVisible();
  await expect(summary.getByText("인천 8월 20일 · 판교 8월 19일 관측 기준")).toBeVisible();
  await expect(summary.getByText(/정상|안전|문제없음/)).toHaveCount(0);
  await summary.getByRole("button", { name: "다른 현장 2곳 전체 보기" }).click();
  await expect(page.getByTestId("candidate-sites")).toBeVisible();
});

test("candidate A manually moves between two image-led attention cases", async ({ page }) => {
  const carousel = page.getByRole("region", { name: "확인 필요 현장 캐러셀" });
  const pagination = page.locator(".candidate-attention-pagination");
  await expect(carousel).toBeVisible();
  await expect(carousel.getByRole("button", { name: /서초 복합물류센터/ })).toBeVisible();
  await expect(carousel.getByRole("button", { name: /김포 제조공장/ })).toBeAttached();
  await expect(page.getByText("1 / 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "이전 현장" })).toBeDisabled();

  const geometry = await carousel.evaluate((element) => {
    const slides = Array.from(element.querySelectorAll<HTMLElement>(".candidate-attention-slide"));
    return {
      viewportWidth: element.clientWidth,
      slideWidths: slides.map((slide) => slide.offsetWidth),
      pageGap: slides[1].offsetLeft - slides[0].offsetLeft - slides[0].offsetWidth,
    };
  });
  expect(geometry.slideWidths).toHaveLength(2);
  expect(geometry.slideWidths.every((width) => Math.abs(width - geometry.viewportWidth) <= 1)).toBe(true);
  expect(geometry.pageGap).toBeGreaterThanOrEqual(12);

  const box = await carousel.boundingBox();
  if (!box) throw new Error("Attention carousel has no bounding box");
  await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.5, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByText("2 / 2", { exact: true })).toBeVisible();
  await expect(pagination.getByText("김포 제조공장", { exact: true })).toBeVisible();
  await expect.poll(() => carousel.evaluate((element) => {
    const target = element.querySelectorAll<HTMLElement>(".candidate-attention-slide")[1];
    return Math.abs(target.offsetLeft - element.scrollLeft);
  })).toBeLessThanOrEqual(1);

  await page.getByRole("button", { name: "이전 현장" }).click();
  await expect(page.getByText("1 / 2", { exact: true })).toBeVisible();
  await expect(pagination.getByText("서초 복합물류센터", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "다음 현장" }).click();
  await expect(page.getByText("2 / 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "다음 현장" })).toBeDisabled();

  await carousel.getByRole("button", { name: /김포 제조공장/ }).click();
  await expect(page.getByRole("heading", { name: "김포 제조공장" })).toBeVisible();
  await expect(page.getByText(/동측 골조 구역의 형상 변화/)).toBeVisible();
});

test("uses distinct synthetic visual assets and opens grounded evidence", async ({ page }) => {
  const seochoImage = page.getByRole("img", { name: "합성 데이터로 만든 서초 복합물류센터 건설 현장 항공 관측 이미지" });
  const gimpoImage = page.getByRole("img", { name: "합성 데이터로 만든 김포 제조공장 골조 공사 항공 관측 이미지" });
  await expect(seochoImage).toBeVisible();
  await expect(seochoImage).toHaveJSProperty("complete", true);
  await expect(gimpoImage).toHaveJSProperty("complete", true);

  await page.getByRole("button", { name: /서초 복합물류센터, 남측 토공 구역/ }).click();
  await expect(page.getByRole("heading", { name: "서초 복합물류센터" })).toBeVisible();
  await expect(page.getByText(/유효 촬영 범위가 61%/)).toBeVisible();
  await expect(page.getByText("업무 영향")).toBeVisible();
  await expect(page.getByText("맥락 확인 전 확정 불가")).toBeVisible();
});

test("question entry explains limits instead of claiming automatic decisions", async ({ page }) => {
  await page.getByRole("button", { name: /왜 먼저 봐야 하나요/ }).click();
  await expect(page.getByRole("heading", { name: "KSI의 설명" })).toBeVisible();
  await expect(page.getByText(/절대 물량이나 일정 영향은 판단하지 않았습니다/)).toBeVisible();
  await expect(page.getByText(/자동 진행|장애물|안전 확인/)).toHaveCount(0);
});

test("candidate navigation remains fixed while lower-site variants change", async ({ page }) => {
  const nav = page.getByRole("navigation", { name: "후보 주요 메뉴" });
  await expect(nav.getByRole("button")).toHaveCount(5);
  await expect(nav).toContainText("홈");
  await expect(nav).toContainText("현장");
  await expect(nav).toContainText("질문");
  await expect(nav).toContainText("알림");
  await expect(nav).toContainText("더보기");
  await nav.getByRole("button", { name: "현장" }).click();
  await expect(page.getByTestId("candidate-sites")).toBeVisible();
  await expect(page.getByRole("heading", { name: "현장" })).toBeVisible();
});

test("has no horizontal overflow and keeps primary touch targets at least 44px", async ({ page }) => {
  const result = await page.evaluate(() => {
    const viewport = document.querySelector<HTMLElement>('[data-testid="mobile-app-viewport"]')!;
    const scroll = document.querySelector<HTMLElement>('[data-testid="mobile-scroll"]')!;
    const targets = Array.from(document.querySelectorAll<HTMLElement>(".candidate-switcher button, .candidate-attention-heading button, .candidate-attention-slide, .candidate-attention-pagination button, .candidate-ask, .candidate-remaining button, .candidate-bottom-nav button"));
    return {
      viewportWidth: viewport.clientWidth,
      scrollWidth: scroll.scrollWidth,
      smallestTarget: Math.min(...targets.map((target) => target.getBoundingClientRect().height)),
    };
  });

  expect(result.scrollWidth).toBeLessThanOrEqual(result.viewportWidth + 1);
  expect(result.smallestTarget).toBeGreaterThanOrEqual(44);
});
