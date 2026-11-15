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
  // 선택 상자는 작업구역(0), A(1), B(2) 순서다.
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
  await expect(main).toContainText("절토");
  await expect(main).toContainText("성토");
  await expect(main).toContainText("순변화");
  await expect(main).toContainText("정확도 평가는 아직 확인되지 않았습니다");
  await expectNoHorizontalOverflow(page);
});
