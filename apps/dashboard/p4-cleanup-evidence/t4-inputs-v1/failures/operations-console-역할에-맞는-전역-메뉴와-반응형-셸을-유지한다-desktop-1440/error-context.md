# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: operations-console.spec.ts >> 역할에 맞는 전역 메뉴와 반응형 셸을 유지한다
- Location: e2e/operations-console.spec.ts:84:5

# Error details

```
Error: expect(page).toHaveScreenshot(expected) failed

  113137 pixels (ratio 0.08 of all image pixels) are different.

  Snapshot: home.png

Call log:
  - Expect "toHaveScreenshot(home.png)" with timeout 5000ms
    - verifying given screenshot expectation
  - taking page screenshot
    - disabled all CSS animations
  - waiting for fonts to load...
  - fonts loaded
  - 113137 pixels (ratio 0.08 of all image pixels) are different.
  - waiting 100ms before taking screenshot
  - taking page screenshot
    - disabled all CSS animations
  - waiting for fonts to load...
  - fonts loaded
  - captured a stable screenshot
  - 113137 pixels (ratio 0.08 of all image pixels) are different.

```

# Page snapshot

```yaml
- generic [active] [ref=f2e1]:
  - link "본문으로 건너뛰기" [ref=f2e2] [cursor=pointer]:
    - /url: "#main-content"
  - navigation "주 메뉴" [ref=f2e3]:
    - generic [ref=f2e4]:
      - generic [ref=f2e5]: KSI
      - generic [ref=f2e6]:
        - generic [ref=f2e7]: 현장 지능
        - generic [ref=f2e8]: SITE INTELLIGENCE
    - button "검색 · 이동 CtrlK" [ref=f2e10]:
      - generic [ref=f2e14]: 검색 · 이동
      - generic [ref=f2e15]: CtrlK
    - generic [ref=f2e16]:
      - generic [ref=f2e17]:
        - link "홈" [ref=f2e18] [cursor=pointer]:
          - /url: /
        - link "현장 5" [ref=f2e24] [cursor=pointer]:
          - /url: /sites
          - generic [ref=f2e25]: 현장
          - generic [ref=f2e30]: "5"
        - link "작업" [ref=f2e31] [cursor=pointer]:
          - /url: /field
      - generic [ref=f2e37]:
        - generic [ref=f2e38]: 운영 지원
        - link "Dock·Edge 지원 범위" [ref=f2e39] [cursor=pointer]:
          - /url: /coming-soon/fleet
    - generic [ref=f2e45]:
      - generic [ref=f2e46]: L
      - generic [ref=f2e47]:
        - generic [ref=f2e48]: local-admin
        - generic [ref=f2e49]: 관리자
      - button "로그아웃" [ref=f2e51]
  - generic [ref=f2e52]:
    - banner [ref=f2e53]:
      - paragraph [ref=f2e54]: 홈
    - main [ref=f2e55]:
      - heading "홈" [level=1] [ref=f2e56]
      - generic [ref=f2e57]:
        - generic [ref=f2e58]:
          - paragraph [ref=f2e59]:
            - text: 전체 5곳·
            - generic [ref=f2e60]: 확인 필요 —
          - generic [ref=f2e61]:
            - link "받은 업무" [ref=f2e62] [cursor=pointer]:
              - /url: /field/inbox
            - link "현장 전체" [ref=f2e63] [cursor=pointer]:
              - /url: /sites
        - paragraph [ref=f2e64]: 일부 현장 또는 작업 원장을 불러오지 못해 확인 필요 건수를 추측하지 않습니다. 각 현장 화면에서 다시 확인하세요.
        - paragraph [ref=f2e65]: 외부 결과의 검토·승인 대기 여부를 확인할 수 없습니다. 확인할 결과가 없다는 뜻이 아닙니다.
        - region [ref=f2e66]:
          - generic [ref=f2e67]:
            - generic [ref=f2e68]:
              - paragraph [ref=f2e69]: 현장 인텔리전스
              - heading "확인이 필요한 현장" [level=2] [ref=f2e70]
            - generic [ref=f2e71]:
              - button "이전 현장" [disabled] [ref=f2e72]
              - button "다음 현장" [ref=f2e75]
          - region "확인 필요 현장 캐러셀" [ref=f2e78]:
            - article [ref=f2e79]:
              - generic [ref=f2e80]:
                - generic [ref=f2e87]:
                  - text: 연결된 이미지 없음
                  - paragraph [ref=f2e88]: 현장 원장에 등록된 관측 이미지가 없습니다.
                - generic [ref=f2e89]:
                  - generic [ref=f2e90]: E2E 승인 검토 현장
                  - generic [ref=f2e91]: 2026. 8. 25. 09:10
              - generic [ref=f2e92]:
                - generic [ref=f2e93]:
                  - paragraph [ref=f2e94]: 승인 대기
                  - heading "E2E 과거 읽기 전용 · 작업 범위 승인" [level=3] [ref=f2e95]
                  - paragraph [ref=f2e96]: 조사 범위 1개 구역과 목적을 검토해야 합니다.
                - link "작업 맥락 보기" [ref=f2e97] [cursor=pointer]:
                  - /url: /field/work-orders/obs-work-00000001
            - article [ref=f2e100]:
              - generic [ref=f2e101]:
                - generic [ref=f2e108]:
                  - text: 연결된 이미지 없음
                  - paragraph [ref=f2e109]: 현장 원장에 등록된 관측 이미지가 없습니다.
                - generic [ref=f2e110]:
                  - generic [ref=f2e111]: E2E 결과 검토 현장
                  - generic [ref=f2e112]: 2026. 8. 25. 09:12
              - generic [ref=f2e113]:
                - generic [ref=f2e114]:
                  - paragraph [ref=f2e115]: 결과 준비
                  - heading "E2E 과거 읽기 전용 · 결과 검토 기록" [level=3] [ref=f2e116]
                  - paragraph [ref=f2e117]: 합성 E2E 상태 전이이며 운영·장비 증거가 아님
                - link "결과와 근거 보기" [ref=f2e118] [cursor=pointer]:
                  - /url: /field/work-orders/obs-work-00000003
          - generic [ref=f2e121]:
            - generic "2개 현장 중 1번째" [ref=f2e122]:
              - 'button "1번째 현장: E2E 승인 검토 현장" [ref=f2e123]'
              - 'button "2번째 현장: E2E 결과 검토 현장" [ref=f2e125]'
            - paragraph [ref=f2e127]: E2E 승인 검토 현장
        - region [ref=f2e128]:
          - generic [ref=f2e129]:
            - generic [ref=f2e130]:
              - paragraph [ref=f2e131]: 현장 준비
              - heading "초기 설정이 필요한 현장" [level=2] [ref=f2e132]
              - paragraph [ref=f2e133]: 첫 관측을 시작하기 위해 현장 범위 설정이나 작업 준비가 필요합니다.
            - link "현장 전체" [ref=f2e134] [cursor=pointer]:
              - /url: /sites
          - list [ref=f2e135]:
            - listitem [ref=f2e136]:
              - generic [ref=f2e137]:
                - generic [ref=f2e138]:
                  - link "E2E 승인 검토 현장" [ref=f2e139] [cursor=pointer]:
                    - /url: /sites/e2e-site-review
                  - generic [ref=f2e140]: 미매핑
                - generic [ref=f2e141]: "01"
              - paragraph [ref=f2e142]: 첫 기준 관측을 준비하세요.
              - paragraph [ref=f2e143]: 현장 범위가 준비되었습니다. 관측 작업을 만들 수 있습니다.
              - link "새 관측 시작" [ref=f2e144] [cursor=pointer]:
                - /url: /sites/e2e-site-review/observations/new
                - text: 새 관측 시작
                - generic [ref=f2e145]: →
        - region [ref=f2e146]:
          - generic [ref=f2e147]:
            - generic [ref=f2e148]:
              - heading "최근 업데이트" [level=2] [ref=f2e149]
              - paragraph [ref=f2e150]: 결과와 사람이 정리한 안건만 표시합니다.
            - link "현장 전체" [ref=f2e151] [cursor=pointer]:
              - /url: /sites
          - generic [ref=f2e152]:
            - link "E2E 관측 완료 현장, 최근 조사, E2E 과거 읽기 전용 · 완료 기록" [ref=f2e153] [cursor=pointer]:
              - /url: /field/work-orders/obs-work-00000004
              - generic [ref=f2e154]:
                - generic [ref=f2e155]:
                  - paragraph [ref=f2e156]: 최근 조사 · E2E 관측 완료 현장
                  - generic [ref=f2e157]: 연결된 미리보기 없음
                  - generic [ref=f2e158]: 2026. 8. 25. 09:13
                - heading "E2E 과거 읽기 전용 · 완료 기록" [level=3] [ref=f2e159]
                - paragraph [ref=f2e160]: 조사 결과가 작업 원장에 기록되었습니다.
                - generic [ref=f2e161]: 내용 보기
            - link "E2E 관측 진행 현장, 현재 원장, 등록된 대기 작업 없음" [ref=f2e164] [cursor=pointer]:
              - /url: /sites/e2e-site-progress
              - generic [ref=f2e165]:
                - generic [ref=f2e166]:
                  - paragraph [ref=f2e167]: 현재 원장 · E2E 관측 진행 현장
                  - generic [ref=f2e168]: 연결된 미리보기 없음
                  - generic [ref=f2e169]: 현장 갱신 2026. 8. 25. 09:02
                - heading "등록된 대기 작업 없음" [level=3] [ref=f2e170]
                - paragraph [ref=f2e171]: 현재 KSI 작업 원장 기준이며 현장 전체의 정상이나 안전을 의미하지 않습니다.
                - generic [ref=f2e172]: 내용 보기
  - alert [ref=f2e175]
```

# Test source

```ts
  10  |     axe: {
  11  |       run: () => Promise<{
  12  |         violations: Array<{ id: string; impact: string | null; nodes: unknown[] }>;
  13  |       }>;
  14  |     };
  15  |   }
  16  | }
  17  | 
  18  | async function login(page: Page) {
  19  |   await page.goto("/");
  20  |   if (page.url().includes("/login")) {
  21  |     const primaryLogin = page.getByRole("button", {
  22  |       name: /개발 Operations Console 시작|조직 계정으로 로그인/,
  23  |     });
  24  |     await primaryLogin.click();
  25  |     const accountPicker = page.getByRole("button", { name: /기본 개발 계정으로 계속/ });
  26  |     const hasAccountPicker = await accountPicker
  27  |       .waitFor({ state: "visible", timeout: 5_000 })
  28  |       .then(() => true)
  29  |       .catch(() => false);
  30  |     if (hasAccountPicker) {
  31  |       await accountPicker.click();
  32  |     }
  33  |   }
  34  |   await expect(page).toHaveURL(/\/$/);
  35  |   await expect(page.getByRole("main")).toBeVisible();
  36  | }
  37  | 
  38  | async function expectNoHorizontalOverflow(page: Page) {
  39  |   const overflow = await page.evaluate(() => ({
  40  |     documentWidth: document.documentElement.scrollWidth,
  41  |     viewportWidth: document.documentElement.clientWidth,
  42  |   }));
  43  |   expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
  44  | }
  45  | 
  46  | async function expectNoSeriousAxeViolations(page: Page) {
  47  |   await page.addScriptTag({ path: axePath });
  48  |   const violations = await page.evaluate(async () => {
  49  |     const result = await window.axe.run();
  50  |     return result.violations.filter(
  51  |       (violation) => violation.impact === "critical" || violation.impact === "serious",
  52  |     );
  53  |   });
  54  |   expect(violations).toEqual([]);
  55  | }
  56  | 
  57  | async function expectMarkedTouchTargets(page: Page) {
  58  |   const tooSmall = await page.locator(".tap-target, .btn, .input, nav a").evaluateAll((elements) =>
  59  |     elements.flatMap((element) => {
  60  |       const node = element as HTMLElement;
  61  |       const style = window.getComputedStyle(node);
  62  |       if (
  63  |         style.display === "none" ||
  64  |         style.visibility === "hidden" ||
  65  |         node.getAttribute("aria-hidden") === "true"
  66  |       ) {
  67  |         return [];
  68  |       }
  69  |       const rect = node.getBoundingClientRect();
  70  |       if (rect.width === 0 || rect.height === 0) return [];
  71  |       return rect.width + 0.5 < 44 || rect.height + 0.5 < 44
  72  |         ? [{ text: node.textContent?.trim().slice(0, 40) ?? "", width: rect.width, height: rect.height }]
  73  |         : [];
  74  |     }),
  75  |   );
  76  |   expect(tooSmall).toEqual([]);
  77  | }
  78  | 
  79  | test.beforeEach(async ({ page }) => {
  80  |   await login(page);
  81  |   await page.goto("/");
  82  | });
  83  | 
  84  | test("역할에 맞는 전역 메뉴와 반응형 셸을 유지한다", async ({ page }, testInfo) => {
  85  |   const isDesktop = testInfo.project.name.startsWith("desktop");
  86  |   const navigation = page.getByRole("navigation", {
  87  |     name: isDesktop ? "주 메뉴" : "하단 메뉴",
  88  |   });
  89  |   await expect(navigation).toBeVisible();
  90  | 
  91  |   const expectedLinks = isDesktop
  92  |     ? [["/", "홈"], ["/sites", "현장"], ["/field", "작업"]]
  93  |     : [["/", "홈"], ["/sites", "현장"], ["/field", "작업"], ["/more", "더보기"]];
  94  |   for (const [href, label] of expectedLinks) {
  95  |     const link = navigation.locator(`a[href="${href}"]`);
  96  |     await expect(link).toBeVisible();
  97  |     await expect(link).toContainText(label);
  98  |   }
  99  | 
  100 |   if (!isDesktop) {
  101 |     for (const link of await navigation.getByRole("link").all()) {
  102 |       const box = await link.boundingBox();
  103 |       expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  104 |     }
  105 |   }
  106 |   await expectNoHorizontalOverflow(page);
  107 |   // 합성 빈 데이터 스택만 결정적 snapshot 정본으로 삼는다. 외부 Tailnet/Staging은
  108 |   // 실제 원장 값이 계속 바뀌므로 레이아웃·overflow·접근성만 검증한다.
  109 |   if (!process.env.KSI_DASHBOARD_E2E_BASE_URL) {
> 110 |     await expect(page).toHaveScreenshot("home.png", {
      |                        ^ Error: expect(page).toHaveScreenshot(expected) failed
  111 |       animations: "disabled",
  112 |       // `mask` uses Playwright's fluorescent magenta by default. The observed
  113 |       // timestamp is intentionally volatile, but the baseline itself is also
  114 |       // used for product review, so retain the neutral footer surface instead
  115 |       // of introducing a development-only colour into the capture.
  116 |       maskColor: "#ffffff",
  117 |       fullPage: true,
  118 |       // 합성 WorkOrder도 생성 시각을 Core 원장에 기록한다. 이미지 유무에 따라
  119 |       // shrink-0 클래스가 달라지는 구현 세부에 기대지 않고, 카드의 시간 표기 전체만
  120 |       // 마스크하여 레이아웃·대비·상호작용 변화는 계속 검출한다.
  121 |       mask: [page.locator("article span.num")],
  122 |       // Linux Chromium은 카드 내부 한국어 글꼴의 서브픽셀 안티앨리어싱만으로
  123 |       // 2,000~3,200px 차이를 낼 수 있다. 이 한계는 390px 화면의 약 1%이며,
  124 |       // 카드 구조·간격·색상 같은 실제 회귀는 그보다 크게 검출된다.
  125 |       maxDiffPixels: 3_500,
  126 |     });
  127 |   }
  128 | });
  129 | 
  130 | test("Home은 합성 운영 원장의 작업·현장 우선순위를 보여 준다", async ({ page }) => {
  131 |   test.skip(Boolean(process.env.KSI_DASHBOARD_E2E_BASE_URL), "외부 원장은 읽기 전용이며 fixture를 전제하지 않습니다.");
  132 |   await page.goto("/");
  133 |   const carousel = page.getByRole("region", { name: "확인 필요 현장 캐러셀" });
  134 |   await expect(carousel).toBeVisible();
  135 |   // The four historical records are excluded unless they need a decision. The
  136 |   // only two decision candidates are the awaiting-approval and review-ready rows.
  137 |   await expect(carousel.getByRole("article")).toHaveCount(2);
  138 |   await expect(carousel.getByRole("heading", { name: "E2E 과거 읽기 전용 · 작업 범위 승인" })).toBeVisible();
  139 |   await expect(carousel.getByRole("heading", { name: "E2E 과거 읽기 전용 · 결과 검토 기록" })).toBeVisible();
  140 | 
  141 |   const initialSetup = page.getByRole("region", { name: "초기 설정이 필요한 현장" });
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
```