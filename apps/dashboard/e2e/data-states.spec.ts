import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

// 자료가 들어 있는 화면 검증. 기본 시드에는 관측·분석 결과가 없어 다른 스펙이 보지 못하는
// 화면을 본다. `node scripts/run-data-state-stack.mjs`가 띄운 합성 픽스처 스택이 있을 때만
// 돌고, 접속 정보 파일 경로를 KSI_DATA_STATE_INFO_FILE로 받는다(없으면 건너뜀).
// 합성 DSM(2×2)이라 현장·정확도·고객 수락 증거가 아니다.
const infoFile = process.env.KSI_DATA_STATE_INFO_FILE;
const info = infoFile
  ? (JSON.parse(readFileSync(infoFile, "utf8")) as {
      siteId: string;
      workAreaId: string;
      analysisId: string;
      analysisIds: string[];
      operatorToken: string;
    })
  : undefined;

test.skip(!info, "KSI_DATA_STATE_INFO_FILE이 없어 데이터 상태 스택을 쓰지 않습니다.");
test.use({ baseURL: process.env.KSI_DATA_STATE_BASE_URL ?? "http://127.0.0.1:3231" });

async function login(page: Page) {
  await page.goto("/login");
  await page.locator("#token").fill(info!.operatorToken);
  await page.getByRole("button", { name: "로그인" }).click();
  // 로그인 화면에도 main이 있어, 이동이 끝난 뒤에야 다음 화면으로 간다.
  await expect(page).not.toHaveURL(/\/login/);
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
}

test("자료 패널은 등록된 관측 2건과 검사 기록을 보이고, 정보 패널은 측정값을 보인다", async ({ page }) => {
  await login(page);
  await page.goto(`/sites/${info!.siteId}?panel=materials&workAreaId=${info!.workAreaId}`);
  const body = page.locator("body");
  await expect(body).toContainText("dsm-analysis-local-baseline.bin");
  await expect(body).toContainText("dsm-analysis-local-current.bin");
  await expect(body).toContainText("검사 결과 기록됨");

  // 좁은 화면에서는 자료 패널이 하단 시트로 열려 "정보" 버튼을 가린다. 시트를 닫고 누른다.
  // 시트는 하이드레이션 뒤에 열리므로 네트워크가 잦아든 뒤에 본다.
  await page.waitForLoadState("networkidle");
  const closeSheet = page.locator("button", { hasText: /^닫기$/ }).locator("visible=true");
  if (await closeSheet.count()) await closeSheet.first().click();
  await page.getByRole("button", { name: "정보" }).first().click();
  await expect(body).toContainText("EPSG:5186");
  await expect(body).toContainText("EPSG:5773");
  await expect(body).toContainText("2 × 2 픽셀");
  await expectNoHorizontalOverflow(page);
});

test("자료 섹션은 등록된 자료를 표로 보이고 선택·검색·등록 진행을 곁에 둔다", async ({ page }) => {
  await login(page);
  await page.goto(`/sites/${info!.siteId}/data?workAreaId=${info!.workAreaId}`);
  await page.waitForLoadState("networkidle");
  const rows = page.locator("[data-asset-row]");
  await expect(rows.filter({ hasText: "dsm-analysis-local-baseline.bin" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "dsm-analysis-local-current.bin" })).toHaveCount(1);

  // 한 건을 고르면 주소가 선택을 갖고, 상세가 인스펙터에 그려진다.
  await rows.filter({ hasText: "dsm-analysis-local-baseline.bin" }).getByRole("link").click();
  await expect(page).toHaveURL(/assetRef=ksa-v1-/);
  await expect(page.getByRole("region", { name: "관측 자료 상세" })).toBeVisible();
  await expect(rows.filter({ hasText: "dsm-analysis-local-baseline.bin" }).getByRole("link")).toHaveAttribute("aria-current", "true");

  // 검색은 이미 불러온 목록 안에서 좁힌다(보이는 양식만 쓴다).
  // 1280px 미만에서는 검색·필터가 접힘 안에 있어 먼저 연다.
  const search = page.getByRole("searchbox", { name: "자료 검색" }).locator("visible=true");
  if (!(await search.count())) await page.locator("summary", { hasText: "검색·필터" }).click();
  await search.fill("current");
  await page.getByRole("button", { name: "적용" }).locator("visible=true").click();
  await expect(rows).toHaveCount(1);
  await expect(page.locator("body")).toContainText("dsm-analysis-local-current.bin");

  // 등록 진행 서랍은 접혀 있다가 열린다.
  // 이동 직후에는 스트리밍 조각이 잠시 겹쳐 있을 수 있어 보이는 서랍만 쓴다.
  const drawer = page.locator('[data-section-drawer="true"]:visible');
  await expect(drawer).not.toHaveAttribute("open", "");
  await drawer.getByText("등록 진행", { exact: true }).click();
  await expect(page.getByRole("region", { name: "등록 진행 중인 작업" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("공간의 영역 보기는 목록·지도·고른 영역의 자료 보기를 한 화면에 둔다", async ({ page }) => {
  await login(page);
  // 공간 뷰어의 맥락 막대에서 영역 보기로 들어간다 — 고른 영역이 그대로 이어진다.
  await page.goto(`/sites/${info!.siteId}?workAreaId=${info!.workAreaId}`);
  await page.getByRole("link", { name: "영역 지도" }).locator("visible=true").click();
  await expect(page).toHaveURL(new RegExp(`panel=areas.*workAreaId=${info!.workAreaId}|workAreaId=${info!.workAreaId}.*panel=areas`));
  const list = page.getByRole("region", { name: "영역 목록" });
  await expect(list.getByRole("link").filter({ hasText: "등록" }).first()).toHaveAttribute("aria-current", "true");
  await expect(page.locator('[data-space-areas-stage="true"] .leaflet-container')).toBeVisible();
  await expectNoHorizontalOverflow(page);

  // 고른 영역의 자료 보기는 공간의 자료 보기로 돌아간다.
  await page.getByRole("link", { name: "이 영역 자료 보기" }).click();
  await expect(page).toHaveURL(new RegExp(`/sites/${info!.siteId}\\?workAreaId=${info!.workAreaId}$`));
});

test("자료 검색은 파일명으로 목록을 좁힌다", async ({ page }) => {
  await login(page);
  await page.goto(`/sites/${info!.siteId}?panel=materials&workAreaId=${info!.workAreaId}`);
  // 자료 패널이 한 문서에 둘 이상 그려질 수 있어 보이는 입력만 쓴다.
  await page.getByLabel("자료 검색").locator("visible=true").fill("baseline");
  await page.getByRole("button", { name: "검색·필터 적용" }).locator("visible=true").click();
  const body = page.locator("body");
  await expect(body).toContainText("dsm-analysis-local-baseline.bin");
  await expect(body).not.toContainText("dsm-analysis-local-current.bin");
});

test("두 시점 비교는 A·B를 주소에 남기고, 준비 기록을 못 읽으면 빈 목록으로 단정하지 않는다", async ({ page }) => {
  await login(page);
  await page.goto(`/sites/${info!.siteId}?mode=compare&workAreaId=${info!.workAreaId}`);
  // 선택 상자는 영역(0), A(1), B(2) 순서다.
  await page.locator("select").nth(1).selectOption({ index: 1 });
  // A 선택의 이동이 끝나야 B 칸이 A를 주소에 싣는다. 사람이 두 칸을 고르는 속도로 맞춘다.
  await expect(page).toHaveURL(/visualAAssetRef=/);
  await page.locator("select").nth(2).selectOption({ index: 2 });
  await expect(page).toHaveURL(/visualAAssetRef=.+&visualBAssetRef=/);
  // 이 픽스처에는 공간 자료 전달 레인이 없어 준비 기록 조회가 실패한다. 이때 화면은
  // 빈 비교 칸이 아니라 "불러오지 못함"을 말해야 한다.
  await expect(page.getByRole("main")).toContainText("준비 기록을 불러오지 못했습니다");
  await expectNoHorizontalOverflow(page);
});

test("분석 이력과 결과는 완료 상태·수치·정확도 미확인 고지를 함께 보인다", async ({ page }) => {
  await login(page);
  await page.goto(`/sites/${info!.siteId}/analysis?workAreaId=${info!.workAreaId}`);
  const main = page.getByRole("main");
  await expect(main).toContainText("실행 완료");
  await expect(main).toContainText("정확도 미확인");
  await expect(main).toContainText("0.01 m³");
  await expect(main).toContainText("이 기록은 정확도 보증이 아닙니다");
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/sites/${info!.siteId}?mode=results&workAreaId=${info!.workAreaId}&analysisId=${info!.analysisId}`,
  );
  await expect(main).toContainText("깎임");
  await expect(main).toContainText("쌓임");
  await expect(main).toContainText("순변화");
  await expect(main).toContainText("불확실성 미기록");
  await expect(main).toContainText("참고용 · 보증 아님");
  await expectNoHorizontalOverflow(page);
});

test("두 주기 결과는 관측일 순으로 비교되고, 검토를 남기면 결과 화면에 반영된다", async ({ page }) => {
  await login(page);
  const [first, second] = info!.analysisIds;
  const results = (id: string) =>
    `/sites/${info!.siteId}?mode=results&workAreaId=${info!.workAreaId}&analysisId=${id}`;
  const main = page.getByRole("main");

  // t1→t2 결과에서 t0→t1 결과가 같은 영역·임계값·셀 크기이므로 한 차트에 함께 놓인다.
  await page.goto(results(second!));
  await expect(main).toContainText("이전 결과와 비교");
  await expect(main).toContainText("비교 조건");
    await expect(main.getByRole("table", { name: /관측일별 깎임과 쌓임/ }).getByRole("row")).toHaveCount(3);
  await expectNoHorizontalOverflow(page);

  // 지도 타일(제3자)을 요청하지 않고 계산 격자만 연다.
  const tileRequests: string[] = [];
  page.on("request", (request) => { if (request.url().includes("openstreetmap")) tileRequests.push(request.url()); });
  await main.getByRole("button", { name: "계산·제외 영역 보기" }).click();
  await expect(main.getByRole("img", { name: /계산 범위 격자/ })).toBeVisible();
  await expect(main.getByRole("button", { name: /지도에서 계산 범위 보기/ })).toHaveCount(0);
  expect(tileRequests).toEqual([]);

  // 검토를 남기면 같은 결과의 화면 상태가 바뀐다. 다른 결과에는 번지지 않는다.
  await page.goto(`/sites/${info!.siteId}/analysis?workAreaId=${info!.workAreaId}&analysisId=${second!}`);
  const form = page.getByRole("group", { name: "검토 결정 선택" });
  await form.getByLabel("추가 확인·조치 필요").check();
  await page.getByLabel(/검토 의견/).fill(`e2e 합성 검토 ${test.info().project.name}: 입력 시점 재확인 필요`);
  await page.getByRole("button", { name: "검토 기록 추가" }).click();
  await expect(page.getByText(`e2e 합성 검토 ${test.info().project.name}: 입력 시점 재확인 필요`)).toBeVisible();

  await page.goto(results(second!));
  await expect(main).toContainText("검토됨 · 추가 확인 필요");
  // 검토는 그 결과에만 붙는다 — 이 시험은 첫 결과를 검토하지 않는다.
  await page.goto(results(first!));
  await expect(main).toContainText("검토 기록 없음");
});
