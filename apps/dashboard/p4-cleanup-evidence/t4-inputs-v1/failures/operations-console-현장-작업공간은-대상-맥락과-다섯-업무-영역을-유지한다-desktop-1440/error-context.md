# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: operations-console.spec.ts >> 현장 작업공간은 대상 맥락과 다섯 업무 영역을 유지한다
- Location: e2e/operations-console.spec.ts:209:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('heading', { name: '다음 행동' })
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for getByRole('heading', { name: '다음 행동' })

```

```yaml
- link "본문으로 건너뛰기":
  - /url: "#main-content"
- navigation "주 메뉴":
  - text: 현장 지능 SITE INTELLIGENCE
  - button "검색 · 이동 CtrlK"
  - link "홈":
    - /url: /
  - link "현장 5":
    - /url: /sites
  - link "작업":
    - /url: /field
  - text: 운영 지원
  - link "Dock·Edge 지원 범위":
    - /url: /coming-soon/fleet
  - text: local-admin 관리자
  - button "로그아웃"
- banner:
  - link "현장으로 이동":
    - /url: /sites/e2e-site-workspace
    - text: 현장
  - paragraph: 현장 상세
- main:
  - heading "현장 상세" [level=1]
  - heading "E2E 현장 작업공간" [level=2]
  - text: 초기 매핑 중 최신 관측 알 수 없음
  - link "새 관측 시작":
    - /url: /sites/e2e-site-workspace/observations/new
  - navigation "현장 상세 화면":
    - link "관측":
      - /url: /sites/e2e-site-workspace
    - link "분석":
      - /url: /sites/e2e-site-workspace?section=analysis
    - link "공간 자산":
      - /url: /sites/e2e-site-workspace?section=spatial-assets
    - link "작업":
      - /url: /sites/e2e-site-workspace?section=work-orders
    - link "외부 결과":
      - /url: /sites/e2e-site-workspace?section=external-results
  - heading "외부 관측 이력" [level=2]
  - paragraph: 현장에 등록된 외부 관측 결과와 보관 근거를 확인합니다.
  - link "외부 관측 이력 열기":
    - /url: /sites/e2e-site-workspace/observations
  - link "새 관측 시작":
    - /url: /sites/e2e-site-workspace/observations/new
- alert
```

# Test source

```ts
  142 |   await expect(initialSetup).toBeVisible();
  143 |   await expect(initialSetup.getByRole("listitem")).toHaveCount(1);
  144 |   await expect(initialSetup).toContainText("E2E 승인 검토 현장");
  145 | });
  146 | 
  147 | test("핵심 전역 화면은 populated 상태에서도 막히거나 가로로 넘치지 않는다", async ({ page }) => {
  148 |   for (const path of ["/sites", "/field"]) {
  149 |     await page.goto(path);
  150 |     await expect(page.getByRole("main")).toBeVisible();
  151 |     await expectNoHorizontalOverflow(page);
  152 |   }
  153 | });
  154 | 
  155 | test("키보드는 내비게이션을 건너뛰고 화면 전환 뒤 본문 맥락을 이어 간다", async ({ page }) => {
  156 |   await page.goto("/");
  157 |   await page.keyboard.press("Tab");
  158 |   const skipLink = page.getByRole("link", { name: "본문으로 건너뛰기" });
  159 |   await expect(skipLink).toBeFocused();
  160 |   await page.keyboard.press("Enter");
  161 |   await expect(page.locator("#main-content")).toBeFocused();
  162 | 
  163 |   const navigation = page.getByRole("navigation", {
  164 |     name: test.info().project.name.startsWith("desktop") ? "주 메뉴" : "하단 메뉴",
  165 |   });
  166 |   await navigation.locator('a[href="/sites"]').click();
  167 |   await expect(page).toHaveURL(/\/sites$/);
  168 |   await expect(page.locator("#main-content")).toBeFocused();
  169 | });
  170 | 
  171 | test("모바일·태블릿의 공용 행동 표면은 44px 터치 기준을 지킨다", async ({ page }, testInfo) => {
  172 |   test.skip(testInfo.project.name.startsWith("desktop"), "coarse pointer 전용 수용 기준입니다.");
  173 |   for (const path of ["/", "/sites", "/field"]) {
  174 |     await page.goto(path);
  175 |     await expect(page.getByRole("main")).toBeVisible();
  176 |     await expectMarkedTouchTargets(page);
  177 |   }
  178 | });
  179 | 
  180 | test("현장 목록은 폭에 맞는 비교 표현과 현장 진입을 유지한다", async ({ page }, testInfo) => {
  181 |   await page.goto("/sites");
  182 |   const siteLink = page.locator('main a[href^="/sites/"]:not([href="/sites/new"])').first();
  183 |   const hasSite = await siteLink
  184 |     .waitFor({ state: "attached", timeout: 5_000 })
  185 |     .then(() => true)
  186 |     .catch(() => false);
  187 |   if (!hasSite && process.env.KSI_DASHBOARD_E2E_BASE_URL) {
  188 |     test.skip(true, "읽기 전용 외부 원장에 표시할 현장이 없습니다.");
  189 |   }
  190 |   if (!hasSite) await expect(siteLink).toBeVisible();
  191 | 
  192 |   if (testInfo.project.name === "desktop-1440") {
  193 |     await expect(page.getByText("진행 단계", { exact: true })).toBeVisible();
  194 |   } else {
  195 |     const compactList = page.getByRole("region", { name: "현장 목록" });
  196 |     await expect(compactList).toBeVisible();
  197 |     await expect(compactList.getByRole("link", { name: "현장 열기" }).first()).toBeVisible();
  198 |     await expect(page.getByText("진행 단계", { exact: true })).toBeHidden();
  199 |   }
  200 |   await expect(page.locator("[data-site-thumbnail]:visible").first()).toBeVisible();
  201 |   if (testInfo.project.name.startsWith("desktop")) {
  202 |     await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toBeVisible();
  203 |   } else {
  204 |     await expect(page.getByRole("link", { name: "현장 등록", exact: true })).toBeHidden();
  205 |   }
  206 |   await expectNoHorizontalOverflow(page);
  207 | });
  208 | 
  209 | test("현장 작업공간은 대상 맥락과 다섯 업무 영역을 유지한다", async ({ page }, testInfo) => {
  210 |   let siteHref: string | null = null;
  211 | 
  212 |   if (
  213 |     !process.env.KSI_DASHBOARD_E2E_BASE_URL ||
  214 |     process.env.KSI_DASHBOARD_E2E_PHASE2 === "1"
  215 |   ) {
  216 |     siteHref = `/sites/${encodeURIComponent(syntheticSiteId)}`;
  217 |   } else {
  218 |     // Tailnet/Staging 검증은 실제 원장을 절대 변경하지 않는다. 등록된 현장이
  219 |     // 있을 때만 첫 현장을 읽어 같은 화면 계약을 확인한다.
  220 |     await page.goto("/sites");
  221 |     const firstSite = page.locator('main a[href^="/sites/"]:not([href="/sites/new"])').first();
  222 |     const hasReadableSite = await firstSite
  223 |       .waitFor({ state: "attached", timeout: 5_000 })
  224 |       .then(() => true)
  225 |       .catch(() => false);
  226 |     if (!hasReadableSite) {
  227 |       test.skip(true, "읽기 전용 검증 대상 현장이 없습니다.");
  228 |     }
  229 |     siteHref = await firstSite.getAttribute("href");
  230 |   }
  231 | 
  232 |   expect(siteHref).not.toBeNull();
  233 |   await page.goto(siteHref!);
  234 |   if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) {
  235 |     await expect(page).toHaveTitle("E2E 현장 작업공간 · 현장 · KSI");
  236 |   }
  237 |   await expect(page.getByRole("heading", { level: 1, name: "현장 상세" })).toHaveCount(1);
  238 |   await expect(page.getByRole("heading", { level: 2, name: "E2E 현장 작업공간" })).toBeVisible();
  239 |   await expect(page.getByRole("link", { name: "현장으로 이동" })).toBeVisible();
  240 |   await expect(page.getByRole("heading", { name: "현장 범위" })).toHaveCount(0);
  241 |   const nextAction = page.getByRole("heading", { name: "다음 행동" });
> 242 |   await expect(nextAction).toBeVisible();
      |                            ^ Error: expect(locator).toBeVisible() failed
  243 | 
  244 |   const labels = ["관측", "분석", "공간 자산", "작업", "외부 결과"];
  245 |   if (testInfo.project.name.startsWith("desktop")) {
  246 |     const siteNavigation = page.getByRole("navigation", { name: "현장 상세 화면" });
  247 |     await expect(siteNavigation).toBeVisible();
  248 |     for (const label of labels) {
  249 |       await expect(siteNavigation.getByRole("link", { name: label, exact: true })).toBeVisible();
  250 |     }
  251 |   } else {
  252 |     const disclosure = page.locator("details summary").filter({ hasText: "현장 메뉴 · 관측" });
  253 |     await expect(disclosure).toBeVisible();
  254 |     await disclosure.click();
  255 |     const siteNavigation = page.getByRole("navigation", { name: "현장 메뉴" });
  256 |     for (const label of labels) {
  257 |       await expect(siteNavigation.getByRole("link", { name: label, exact: true })).toBeVisible();
  258 |     }
  259 |     await expect(page.getByText("노트북에서 계속", { exact: true })).toHaveCount(0);
  260 |     await siteNavigation.getByRole("link", { name: "작업", exact: true }).click();
  261 |     await expect(page).toHaveURL(/section=work-orders/);
  262 |   }
  263 |   await page.goto(`${siteHref}?section=work-orders`);
  264 |   await expect(page.getByText("E2E 외부 산출물 등록", { exact: true })).toBeVisible();
  265 |   await page.reload();
  266 |   await expect(page.getByText("E2E 외부 산출물 등록", { exact: true })).toBeVisible();
  267 | 
  268 |   await page.goto(`${siteHref}?section=external-results`);
  269 |   const unavailableHistory = page.getByText("외부 관측 결과를 불러오지 못했습니다.", { exact: true });
  270 |   const emptyHistory = page.getByRole("heading", { name: "외부 관측 결과가 없습니다", exact: true });
  271 |   await expect(unavailableHistory.or(emptyHistory)).toBeVisible();
  272 |   await expectNoHorizontalOverflow(page);
  273 | });
  274 | 
  275 | test("전역 작업 화면은 결정·진행·완료 원장을 구분하고 모호한 뒤로가기를 두지 않는다", async ({ page }) => {
  276 |   await page.goto("/field");
  277 |   await expect(page.getByRole("link", { name: "작업으로 이동" })).toHaveCount(0);
  278 |   await expect(page.getByRole("button", { name: "뒤로" })).toHaveCount(0);
  279 |   if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) {
  280 |     await expect(page.getByText("E2E 과거 읽기 전용 · 작업 범위 승인", { exact: true })).toBeVisible();
  281 |     await expect(page.getByText("E2E 과거 읽기 전용 · 승인 기록", { exact: true })).toBeVisible();
  282 |     await expect(page.getByText("E2E 과거 읽기 전용 · 결과 검토 기록", { exact: true })).toBeVisible();
  283 |     await expect(page.getByText("E2E 과거 읽기 전용 · 완료 기록", { exact: true })).toBeVisible();
  284 |     await expect(page.getByText("E2E 외부 산출물 등록", { exact: true })).toBeVisible();
  285 |     for (const group of ["결정 필요", "진행 중", "완료"]) {
  286 |       await expect(page.getByRole("heading", { name: group, exact: true })).toBeVisible();
  287 |     }
  288 |   }
  289 | });
  290 | 
  291 | test("작업 상세는 실행 근거가 없으면 관리형 실행을 fail-closed로 숨긴다", async ({ page }) => {
  292 |   test.skip(
  293 |     Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL),
  294 |     "외부 원장은 읽기 전용이며 로컬 합성 evidence gap을 전제하지 않습니다.",
  295 |   );
  296 | 
  297 |   const browserFailures: string[] = [];
  298 |   page.on("console", (message) => {
  299 |     if (message.type() === "error") browserFailures.push(`console: ${message.text()}`);
  300 |   });
  301 |   page.on("pageerror", (error) => browserFailures.push(`pageerror: ${error.message}`));
  302 | 
  303 |   await page.goto("/field");
  304 |   const workOrderLink = page.locator('main a[href^="/field/work-orders/"]').first();
  305 |   await expect(workOrderLink).toBeVisible();
  306 |   const workOrderHref = await workOrderLink.getAttribute("href");
  307 |   expect(workOrderHref).toMatch(/^\/field\/work-orders\/[^/]+$/);
  308 | 
  309 |   await page.goto(workOrderHref!);
  310 |   await expect(
  311 |     page.getByText(
  312 |       "작업 실행 유형을 확인하지 못했습니다. 관리형 실행 상태나 장비 동작을 표시하지 않습니다.",
  313 |       { exact: true },
  314 |     ),
  315 |   ).toBeVisible();
  316 |   await expect(page.getByText("Acquisition progress", { exact: true })).toHaveCount(0);
  317 |   await expect(page.getByText("전문가 복구 정보", { exact: true })).toHaveCount(0);
  318 |   await expect(page.getByRole("link", { name: "수동 임무 복구 열기", exact: true })).toHaveCount(0);
  319 |   await expectNoHorizontalOverflow(page);
  320 |   expect(browserFailures).toEqual([]);
  321 | });
  322 | 
  323 | test("외부 재구성 작업은 승인·운영 중 상태와 등록 UI를 제공한다", async ({ page }, testInfo) => {
  324 |   test.skip(
  325 |     Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL),
  326 |     "외부 원장은 읽기 전용이며 로컬 합성 외부 작업을 전제하지 않습니다.",
  327 |   );
  328 | 
  329 |   await page.goto("/field");
  330 |   const externalWorkOrder = page.getByRole("link", { name: /E2E 외부 산출물 등록/ });
  331 |   await expect(externalWorkOrder).toBeVisible();
  332 |   await externalWorkOrder.click();
  333 | 
  334 |   await expect(page.getByRole("heading", { name: "E2E 외부 산출물 등록" })).toBeVisible();
  335 |   await expect(page.getByRole("heading", { name: "작업 운영" })).toBeVisible();
  336 |   await expect(page.getByText("운영 중", { exact: true })).toBeVisible();
  337 |   await expect(page.getByRole("heading", { name: "재구성 산출물 등록" })).toBeVisible();
  338 |   await expect(page.getByText("등록된 외부 산출물이 없습니다.", { exact: true })).toBeVisible();
  339 |   await expect(page.getByText(/측정 성공|정확도 검증 완료|산출물 검증 완료/)).toHaveCount(0);
  340 | 
  341 |   if (testInfo.project.name.startsWith("desktop")) {
  342 |     await expect(page.getByLabel("정사영상 GeoTIFF")).toBeVisible();
```