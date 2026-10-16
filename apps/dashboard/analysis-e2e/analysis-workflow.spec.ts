import { createHash, randomBytes } from "node:crypto";
import { readFileSync, renameSync, writeFileSync } from "node:fs";
import { expect, test, type Locator } from "@playwright/test";
import { formatNumberKo, formatSignificantKo } from "../src/lib/number-format";

type Selector = { workOrderId: string; submissionRef: string; revision: number };
type ObservationOption = {
  selector: Selector;
  observationEpochId: string;
  captureStartedAt: string;
  captureEndedAt: string;
};
type AnalysisResult = {
  resultId: string;
  reportDigest: string;
  numericResultIdentityDigest: string;
  metrics: {
    cutM3: number;
    fillM3: number;
    netM3: number;
    thresholdM: number;
    uncertaintyM3: number | null;
  };
  limitationCodes: string[];
};
type AnalysisView = {
  analysisId: string;
  siteId: string;
  workAreaId: string;
  baseline: Selector;
  current: Selector;
  executionState: string;
  suitabilityState: string;
  result: AnalysisResult | null;
  authority: Record<string, unknown>;
  blockers: { code: string; epoch: string | null; evidenceRef: string | null; detail: string | null }[];
};
type AnalysisListItemV2 = {
  analysisId: string;
  siteId: string;
  workAreaId: string;
  executionState: string;
  suitabilityState: string;
  createdAt: string;
  resultId: string | null;
  metrics: AnalysisResult["metrics"] | null;
  limitationCount: number;
  analysisHref: string;
};
type AnalysisListPageV2 = { siteId: string; items: AnalysisListItemV2[]; nextCursor: string | null };
type AnalysisEvidencePageV2 = {
  analysisId: string;
  evidenceRevision: number;
  evidenceDigest: string;
  nextCursor: string | null;
  items: Array<Record<string, unknown>>;
};
type AnalysisViewV2 = {
  analysisId: string;
  result: AnalysisResult | null;
  evidenceRevision: number;
  evidenceDigest: string;
};
type EpochEvidence = {
  selector: Selector;
  observationEpochId: string;
  observedSha256: string;
  inputDigest: string;
  inspectionReportDigest: string;
};
type AnalysisEvidence = {
  analysisId: string;
  baseline: EpochEvidence;
  current: EpochEvidence;
  evaluations: unknown[];
  calculation: {
    calculationId: string;
    workAreaDefinitionDigest: string;
    policy: { profileId: string; profileDigest: string };
    runtime: Record<string, unknown>;
  };
  result: AnalysisResult | null;
};

async function revealCoreDetails(container: Locator): Promise<void> {
  const summaries = container.locator("summary").filter({ hasText: "Core 코드" });
  for (const summary of await summaries.all()) await summary.click();
}

async function revealEpochEvidence(container: Locator, observationEpochId: string): Promise<Locator> {
  const item = container.locator("details").filter({ hasText: observationEpochId }).first();
  await item.locator("summary").click();
  return item;
}
type ControlAck = {
  controlId: string;
  status: string;
  verdict?: string;
  reason?: string;
  pendingJobCount?: number;
};
type FixtureManifest = {
  siteId: string;
  workAreaId: string;
  baselineSelector: Selector;
  currentSelector: Selector;
  inspectionReportDigests: string[];
  thirdSelector?: Selector;
  scenario: "normal" | "missing-vertical-reference" | "overlapping-current-nodata-cell" | "viewer-readonly" | "weekly-reuse";
};

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`missing isolated Analysis E2E setting: ${name}`);
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSelector(value: unknown): value is Selector {
  return isRecord(value)
    && typeof value.workOrderId === "string"
    && value.workOrderId.length > 0
    && typeof value.submissionRef === "string"
    && value.submissionRef.length > 0
    && typeof value.revision === "number"
    && Number.isInteger(value.revision)
    && value.revision >= 0;
}

function isFixtureManifest(
  value: unknown,
  expectedScenario: FixtureManifest["scenario"],
): value is FixtureManifest {
  const weekly = expectedScenario === "weekly-reuse";
  return isRecord(value)
    && typeof value.siteId === "string"
    && value.siteId.length > 0
    && typeof value.workAreaId === "string"
    && value.workAreaId.length > 0
    && value.scenario === expectedScenario
    && isSelector(value.baselineSelector)
    && isSelector(value.currentSelector)
    && Array.isArray(value.inspectionReportDigests)
    && value.inspectionReportDigests.length === (weekly ? 3 : 2)
    && value.inspectionReportDigests.every(
      (digest) => typeof digest === "string" && /^sha256:[0-9a-f]{64}$/.test(digest),
    )
    && (weekly ? isSelector(value.thirdSelector) : value.thirdSelector === undefined);
}

async function readFixtureManifest(
  expectedScenario: FixtureManifest["scenario"],
): Promise<FixtureManifest> {
  const manifestPath = `${requiredEnv("KSI_ANALYSIS_E2E_DATA_DIR")}/inspected-fixture.json`;
  let manifest: FixtureManifest | undefined;
  await expect.poll(() => {
    try {
      const parsed: unknown = JSON.parse(readFileSync(manifestPath, "utf8"));
      if (!isFixtureManifest(parsed, expectedScenario)) return false;
      manifest = parsed;
      return true;
    } catch {
      return false;
    }
  }, { timeout: 60_000 }).toBe(true);
  if (manifest === undefined) throw new Error("complete real inspection manifest did not become available");
  return manifest;
}

const coreOrigin = requiredEnv("KSI_ANALYSIS_E2E_CORE_ORIGIN");
const issuerOrigin = requiredEnv("KSI_ANALYSIS_E2E_ISSUER_ORIGIN");
const clientId = requiredEnv("KSI_ANALYSIS_E2E_CLIENT_ID");
const scenarioValue = process.env.KSI_ANALYSIS_E2E_SCENARIO ?? "normal";
if (
  scenarioValue !== "normal"
  && scenarioValue !== "missing-vertical-reference"
  && scenarioValue !== "overlapping-current-nodata-cell"
  && scenarioValue !== "viewer-readonly"
  && scenarioValue !== "weekly-reuse"
) {
  throw new Error(`unsupported Analysis E2E scenario: ${scenarioValue}`);
}
const scenario: FixtureManifest["scenario"] = scenarioValue;
const clientSecret = readFileSync(
  requiredEnv("KSI_ANALYSIS_E2E_CLIENT_SECRET_FILE"),
  "utf8",
).trim();
function equalSelector(left: Selector, right: Selector): boolean {
  return left.workOrderId === right.workOrderId
    && left.submissionRef === right.submissionRef
    && left.revision === right.revision;
}

function pkceChallenge(verifier: string): string {
  return createHash("sha256").update(verifier, "ascii").digest("base64url");
}

async function issueAccessToken(account: string): Promise<string> {
  const state = randomBytes(24).toString("base64url");
  const nonce = randomBytes(24).toString("base64url");
  const verifier = randomBytes(32).toString("base64url");
  const redirectUri = "http://localhost:3231/api/auth/callback/ksi-oidc";
  const authorizeParams = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: redirectUri,
    scope: "openid profile offline_access",
    state,
    nonce,
    code_challenge: pkceChallenge(verifier),
    code_challenge_method: "S256",
    login_hint: account,
  });
  const authorize = new URL("/authorize", issuerOrigin);
  authorize.search = authorizeParams.toString();
  let completed = await fetch(authorize, { redirect: "manual" });
  if (completed.status === 200) {
    authorizeParams.set("account", account);
    completed = await fetch(new URL("/authorize", issuerOrigin), {
      method: "POST",
      redirect: "manual",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: authorizeParams,
    });
  }
  expect(completed.status).toBe(302);
  const location = completed.headers.get("location");
  expect(location).not.toBeNull();
  const callback = new URL(location!, issuerOrigin);
  expect(callback.searchParams.get("state")).toBe(state);
  const code = callback.searchParams.get("code");
  expect(code).not.toBeNull();

  const credentials = Buffer.from(`${clientId}:${clientSecret}`, "ascii").toString("base64");
  const tokenResponse = await fetch(new URL("/token", issuerOrigin), {
    method: "POST",
    headers: {
      authorization: `Basic ${credentials}`,
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code: code!,
      redirect_uri: redirectUri,
      code_verifier: verifier,
    }),
  });
  expect(tokenResponse.status).toBe(200);
  const token = await tokenResponse.json() as { access_token?: unknown };
  expect(typeof token.access_token).toBe("string");
  return token.access_token as string;
}

async function coreGet<T>(path: string, accessToken: string): Promise<T> {
  const response = await fetch(new URL(path, coreOrigin), {
    headers: { authorization: `Bearer ${accessToken}` },
  });
  expect(response.status, `${path}: ${await response.clone().text()}`).toBe(200);
  return await response.json() as T;
}

function resultMetricLabel(value: number): string {
  const rendered = Math.abs(value) > 0 && Math.abs(value) < 0.1
    ? formatSignificantKo(value, 3)
    : formatNumberKo(value, 1);
  return `${rendered} m³`;
}

async function requestRunnerControl(
  action: "APPEND_FAILED_CURRENT_CHECKPOINT_EVALUATION" | "CHECK_NO_WORKER_JOB",
): Promise<ControlAck> {
  const runId = requiredEnv("KSI_ANALYSIS_E2E_RUN_ID");
  const dataDir = requiredEnv("KSI_ANALYSIS_E2E_DATA_DIR");
  const controlId = randomBytes(24).toString("hex");
  const requestPath = `${dataDir}/control-${controlId}.request.json`;
  const pendingPath = `${requestPath}.pending`;
  writeFileSync(pendingPath, JSON.stringify({ version: 1, runId, controlId, action }), {
    flag: "wx",
    mode: 0o600,
  });
  renameSync(pendingPath, requestPath);

  const ackPath = `${dataDir}/control-${controlId}.ack.json`;
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const ack = JSON.parse(readFileSync(ackPath, "utf8")) as ControlAck;
      expect(ack.controlId).toBe(controlId);
      return ack;
    } catch (error) {
      if (!(error instanceof Error) || !("code" in error) || error.code !== "ENOENT") throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`runner did not acknowledge control action ${action}`);
}

test("OIDC 사용자가 실제 검사된 두 관측의 Analysis 결과와 근거를 조회한다", async ({ page }) => {
  test.setTimeout(120_000);
  test.skip(scenario !== "normal", "normal Analysis E2E scenario only");
  const fixture = await readFixtureManifest(scenario);
  expect(fixture.scenario).toBe(scenario);
  const operatorToken = await issueAccessToken("local-admin");
  const foreignToken = await issueAccessToken("local-empty-org-admin");
  const observationResponse = await coreGet<{ items: ObservationOption[] }>(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/analysis-observations`,
    operatorToken,
  );
  const offered = observationResponse.items;
  const baselineOption = offered.find((item) => equalSelector(item.selector, fixture.baselineSelector));
  const currentOption = offered.find((item) => equalSelector(item.selector, fixture.currentSelector));
  expect(baselineOption).toBeDefined();
  expect(currentOption).toBeDefined();

  const foreignResponse = await fetch(new URL(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/analysis-observations`,
    coreOrigin,
  ), { headers: { authorization: `Bearer ${foreignToken}` } });
  expect(foreignResponse.status).toBe(404);

  await page.goto("/login");
  await page.getByRole("button", { name: "개발 Operations Console 시작" }).click();
  await expect(page).toHaveURL("http://localhost:3231/");
  await page.goto(`/sites/${encodeURIComponent(fixture.siteId)}/analysis`);
  await expect(page.getByRole("heading", { name: "현장 분석" })).toBeVisible();

  const workArea = page.getByLabel("작업구역");
  await expect(workArea.locator("option")).toHaveCount(2);
  await workArea.selectOption(fixture.workAreaId);

  for (const [label, expected] of [
    ["기준 관측", baselineOption!],
    ["현재 관측", currentOption!],
  ] as const) {
    const select = page.getByLabel(label);
    const options = await select.locator("option").allTextContents();
    const index = options.findIndex((text) => text.includes(expected.observationEpochId));
    expect(index, `${label} option for ${expected.observationEpochId}`).toBeGreaterThan(0);
    const value = await select.locator("option").nth(index).getAttribute("value");
    expect(value).not.toBeNull();
    await select.selectOption(value!);
  }

  const postPromise = page.waitForResponse((response) =>
    response.request().method() === "POST"
      && response.url().includes(`/api/sites/${fixture.siteId}/work-areas/${fixture.workAreaId}/analyses`),
  );
  await page.getByRole("button", { name: "분석 요청" }).click();
  const submitted = await postPromise;
  expect(submitted.status()).toBe(202);
  const accepted = await submitted.json() as AnalysisView;
  expect(accepted.siteId).toBe(fixture.siteId);
  expect(accepted.workAreaId).toBe(fixture.workAreaId);
  expect(equalSelector(accepted.baseline, fixture.baselineSelector)).toBe(true);
  expect(equalSelector(accepted.current, fixture.currentSelector)).toBe(true);
  expect(accepted.executionState).toBe("QUEUED");

  const detailPath = `/v1/sites/${fixture.siteId}/analyses/${accepted.analysisId}`;
  let detail: AnalysisView | null = null;
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const response = await fetch(new URL(detailPath, coreOrigin), {
      headers: { authorization: `Bearer ${operatorToken}` },
    });
    expect(response.status).toBe(200);
    detail = await response.json() as AnalysisView;
    if (detail.executionState === "COMPLETED" || detail.executionState === "FAILED") break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  expect(detail?.executionState).toBe("COMPLETED");
  expect(detail?.suitabilityState).toBe("PROVISIONAL_ACCURACY_UNVERIFIED");

  const analysisCard = page.getByRole("article").filter({ hasText: accepted.analysisId });
  await expect(analysisCard.getByText("실행 완료", { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "근거 확인" }).click();

  const result = await coreGet<{ result: AnalysisResult; executionState: string }>(
    `${detailPath}/result`,
    operatorToken,
  );
  const evidence = await coreGet<AnalysisEvidence>(`${detailPath}/evidence`, operatorToken);
  for (const suffix of ["", "/result", "/evidence"]) {
    const foreignAnalysisResponse = await fetch(new URL(`${detailPath}${suffix}`, coreOrigin), {
      headers: { authorization: `Bearer ${foreignToken}` },
    });
    expect(foreignAnalysisResponse.status, `foreign organization ${suffix || "detail"}`).toBe(404);
  }
  expect(result.executionState).toBe("COMPLETED");
  expect(detail?.result).not.toBeNull();
  expect(result.result.resultId).toBe(detail?.result?.resultId);
  expect(evidence.analysisId).toBe(accepted.analysisId);
  expect(evidence.result?.resultId).toBe(result.result.resultId);
  expect(evidence.baseline.selector).toEqual(fixture.baselineSelector);
  expect(evidence.current.selector).toEqual(fixture.currentSelector);
  expect(evidence.baseline.inspectionReportDigest).toBe(fixture.inspectionReportDigests[0]);
  expect(evidence.current.inspectionReportDigest).toBe(fixture.inspectionReportDigests[1]);
  expect(evidence.baseline.observedSha256).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(evidence.current.observedSha256).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(result.result).toEqual(detail?.result);

  await expect(analysisCard).toContainText(accepted.analysisId);
  await expect(analysisCard).toContainText(result.result.resultId);
  await expect(analysisCard).toContainText(resultMetricLabel(result.result.metrics.cutM3));
  await expect(analysisCard).toContainText(resultMetricLabel(result.result.metrics.fillM3));
  await expect(analysisCard).toContainText(resultMetricLabel(result.result.metrics.netM3));
  const evidenceRegion = analysisCard.getByRole("region", { name: "근거" });
  const baselineEvidenceItem = await revealEpochEvidence(evidenceRegion, evidence.baseline.observationEpochId);
  const currentEvidenceItem = await revealEpochEvidence(evidenceRegion, evidence.current.observationEpochId);
  await expect(baselineEvidenceItem).toContainText(evidence.baseline.inspectionReportDigest);
  await expect(currentEvidenceItem).toContainText(evidence.current.inspectionReportDigest);
  expect(evidence.baseline.observedSha256).not.toBe(evidence.current.observedSha256);

  const lateEvaluation = await requestRunnerControl("APPEND_FAILED_CURRENT_CHECKPOINT_EVALUATION");
  expect(lateEvaluation).toEqual({
    controlId: lateEvaluation.controlId,
    status: "APPLIED",
    verdict: "REJECTED",
    reason: "CHECKPOINT_COUNT_OUT_OF_RANGE",
  });

  const currentDetail = await coreGet<AnalysisView>(detailPath, operatorToken);
  const currentResult = await coreGet<{
    executionState: string;
    suitabilityState: string;
    result: AnalysisResult | null;
  }>(`${detailPath}/result`, operatorToken);
  const currentEvidence = await coreGet<AnalysisEvidence>(`${detailPath}/evidence`, operatorToken);
  expect(currentDetail.analysisId).toBe(accepted.analysisId);
  expect(currentEvidence.analysisId).toBe(accepted.analysisId);
  expect(currentDetail.executionState).toBe("COMPLETED");
  expect(currentDetail.suitabilityState).toBe("REASSESSMENT_REQUIRED");
  expect(currentDetail.result).toBeNull();
  expect(currentResult).toMatchObject({
    executionState: "COMPLETED",
    suitabilityState: "REASSESSMENT_REQUIRED",
    result: null,
  });
  expect(currentEvidence.result).toBeNull();
  expect(currentEvidence.evaluations).toEqual(evidence.evaluations);
  const historicalCard = page.getByRole("article").filter({ hasText: accepted.analysisId });
  await expect(historicalCard).toContainText("재평가 필요", { timeout: 30_000 });
  await expect(historicalCard).not.toContainText(result.result.resultId);
  await expect(historicalCard).not.toContainText(resultMetricLabel(result.result.metrics.cutM3));
  await expect(historicalCard).not.toContainText(resultMetricLabel(result.result.metrics.fillM3));
  await expect(historicalCard).not.toContainText(resultMetricLabel(result.result.metrics.netM3));

  const remediationPostPromise = page.waitForResponse((response) =>
    response.request().method() === "POST"
      && response.url().includes(`/api/sites/${fixture.siteId}/work-areas/${fixture.workAreaId}/analyses`),
  );
  await page.getByRole("button", { name: "분석 요청" }).click();
  const remediationPost = await remediationPostPromise;
  expect(remediationPost.status()).toBe(202);
  const remediation = await remediationPost.json() as AnalysisView;
  expect(remediation.analysisId).not.toBe(accepted.analysisId);
  expect(remediation.executionState).toBe("NOT_STARTED");
  expect(remediation.suitabilityState).toBe("REMEDIATION_REQUIRED");
  expect(remediation.result).toBeNull();
  expect(remediation.blockers.map((blocker) => blocker.code)).toContain(
    "CHECKPOINT_COUNT_OUT_OF_RANGE",
  );

  const remediationDetail = await coreGet<AnalysisView>(
    `/v2/sites/${fixture.siteId}/analyses/${remediation.analysisId}`,
    operatorToken,
  );
  const remediationEvidence = await coreGet<AnalysisEvidence>(
    `/v1/sites/${fixture.siteId}/analyses/${remediation.analysisId}/evidence`,
    operatorToken,
  );
  expect(remediationDetail).toEqual(remediation);
  expect(remediationEvidence.result).toBeNull();
  expect(remediationEvidence.evaluations).toEqual(expect.arrayContaining([
    expect.objectContaining({
      epoch: "CURRENT",
      outcome: "FAIL",
      reasonCodes: ["CHECKPOINT_COUNT_OUT_OF_RANGE"],
    }),
  ]));
  const remediationCard = page.getByRole("article").filter({ hasText: remediation.analysisId });
  await expect(remediationCard.getByText("시작 전", { exact: true })).toBeVisible();
  await expect(remediationCard.getByText("보완 필요", { exact: true })).toBeVisible();
  await expect(remediationCard).toContainText("CHECKPOINT_COUNT_OUT_OF_RANGE");
  await expect(remediationCard).not.toContainText(result.result.resultId);
  await expect(remediationCard).not.toContainText(resultMetricLabel(result.result.metrics.cutM3));

  const emptyQueue = await requestRunnerControl("CHECK_NO_WORKER_JOB");
  expect(emptyQueue).toEqual({
    controlId: emptyQueue.controlId,
    status: "CHECKED",
    pendingJobCount: 0,
  });
});

test("OIDC 열람자는 저장된 Analysis 결과를 읽고 새 요청은 만들 수 없다", async ({ page }) => {
  test.setTimeout(120_000);
  test.skip(scenario !== "viewer-readonly", "viewer read-only scenario only");
  const fixture = await readFixtureManifest(scenario);
  expect(fixture.scenario).toBe(scenario);
  const operatorToken = await issueAccessToken("local-admin");
  const viewerToken = await issueAccessToken("local-viewer");
  const foreignToken = await issueAccessToken("local-empty-org-admin");
  const analysisCollection = `/v1/sites/${encodeURIComponent(fixture.siteId)}/analyses`;
  const observations = await coreGet<{ items: ObservationOption[] }>(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/analysis-observations`,
    operatorToken,
  );
  const baselineOption = observations.items.find((item) => equalSelector(item.selector, fixture.baselineSelector));
  const currentOption = observations.items.find((item) => equalSelector(item.selector, fixture.currentSelector));
  expect(baselineOption).toBeDefined();
  expect(currentOption).toBeDefined();

  const beforeCreate = await fetch(new URL(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/work-areas/${encodeURIComponent(fixture.workAreaId)}/analyses`,
    coreOrigin,
  ), {
    method: "POST",
    headers: {
      authorization: `Bearer ${operatorToken}`,
      "content-type": "application/json",
      "Idempotency-Key": `viewer-read-${randomBytes(20).toString("hex")}`,
    },
    body: JSON.stringify({ baseline: fixture.baselineSelector, current: fixture.currentSelector }),
  });
  expect(beforeCreate.status, await beforeCreate.clone().text()).toBe(202);
  const accepted = await beforeCreate.json() as AnalysisView;
  expect(accepted.executionState).toBe("QUEUED");
  expect(accepted.siteId).toBe(fixture.siteId);
  expect(accepted.workAreaId).toBe(fixture.workAreaId);

  const detailPath = `/v1/sites/${encodeURIComponent(fixture.siteId)}/analyses/${encodeURIComponent(accepted.analysisId)}`;
  const observed: { detail?: AnalysisView } = {};
  await expect.poll(async () => {
    const detail = await coreGet<AnalysisView>(detailPath, operatorToken);
    observed.detail = detail;
    return detail.executionState;
  }, { timeout: 60_000 }).toBe("COMPLETED");
  const completed = observed.detail;
  if (completed === undefined) throw new Error("operator did not observe completed Analysis");
  expect(completed.suitabilityState).toBe("PROVISIONAL_ACCURACY_UNVERIFIED");
  expect(completed.result).not.toBeNull();

  const result = await coreGet<{ result: AnalysisResult; executionState: string }>(
    `${detailPath}/result`, operatorToken,
  );
  const evidence = await coreGet<AnalysisEvidence>(`${detailPath}/evidence`, operatorToken);
  expect(result.executionState).toBe("COMPLETED");
  expect(result.result.resultId).toBe(completed.result?.resultId);
  expect(evidence.analysisId).toBe(accepted.analysisId);
  expect(evidence.result?.resultId).toBe(result.result.resultId);
  expect(evidence.baseline.inspectionReportDigest).toBe(fixture.inspectionReportDigests[0]);
  expect(evidence.current.inspectionReportDigest).toBe(fixture.inspectionReportDigests[1]);

  for (const suffix of ["", "/result", "/evidence"]) {
    const foreignRead = await fetch(new URL(`${detailPath}${suffix}`, coreOrigin), {
      headers: { authorization: `Bearer ${foreignToken}` },
    });
    expect(foreignRead.status, `foreign organization ${suffix || "detail"}`).toBe(404);
  }

  await page.goto("/login");
  await page.locator("summary").filter({ hasText: "권한별 화면 테스트" }).click();
  await page.getByRole("button", { name: "다른 개발 계정 선택" }).click();
  await expect(page.getByRole("heading", { name: "KSI 로컬 인증 테스트" })).toBeVisible();
  await page.locator("details").filter({ hasText: "권한별 화면 테스트(선택)" }).locator("summary").click();
  await page.getByRole("button", { name: /KSI 개발 열람자/ }).click();
  await expect(page).toHaveURL("http://localhost:3231/");
  await page.goto(
    `/sites/${encodeURIComponent(fixture.siteId)}/analysis?analysisId=${encodeURIComponent(accepted.analysisId)}`,
  );
  await expect(page.getByRole("heading", { name: "현장 분석" })).toBeVisible();
  await expect(page.getByText("분석 기록을 조회할 수 있습니다. 새 분석 요청은 권한 있는 현장 담당자에게 맡겨 주세요.")).toBeVisible();
  await expect(page.getByText("새 분석 요청", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "분석 요청" })).toHaveCount(0);
  const card = page.getByRole("article").filter({ hasText: accepted.analysisId });
  await expect(card.getByText("실행 완료", { exact: true })).toBeVisible();
  await expect(card).toContainText(result.result.resultId);
  await expect(card).toContainText(resultMetricLabel(result.result.metrics.cutM3));
  await expect(card).toContainText(resultMetricLabel(result.result.metrics.fillM3));
  await expect(card).toContainText(resultMetricLabel(result.result.metrics.netM3));
  await page.getByRole("button", { name: "근거 확인" }).click();
  await expect(card.getByRole("region", { name: "근거" })).toBeVisible();
  const evidenceRegion = card.getByRole("region", { name: "근거" });
  const baselineEvidence = await revealEpochEvidence(evidenceRegion, evidence.baseline.observationEpochId);
  const currentEvidence = await revealEpochEvidence(evidenceRegion, evidence.current.observationEpochId);
  await expect(baselineEvidence).toContainText(evidence.baseline.inspectionReportDigest);
  await expect(currentEvidence).toContainText(evidence.current.inspectionReportDigest);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: "작업구역 현황 확인" }).click();
  await expect(page).toHaveURL(`http://localhost:3231/sites/${encodeURIComponent(fixture.siteId)}/work-areas`);
  await expect(page.getByText(/작업구역을 등록하거나 보관하려면/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "사용 중인 작업구역" })).toBeVisible();
  await expect(page.getByRole("button", { name: "등록", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /보관/ })).toHaveCount(0);

  const viewerAnalysesBefore = await coreGet<{ items: AnalysisView[] }>(analysisCollection, viewerToken);
  expect(viewerAnalysesBefore.items.some((item) => item.analysisId === accepted.analysisId)).toBe(true);
  const viewerDetail = await coreGet<AnalysisView>(detailPath, viewerToken);
  const viewerResult = await coreGet<{ result: AnalysisResult; executionState: string }>(
    `${detailPath}/result`, viewerToken,
  );
  const viewerEvidence = await coreGet<AnalysisEvidence>(`${detailPath}/evidence`, viewerToken);
  expect(viewerDetail.analysisId).toBe(accepted.analysisId);
  expect(viewerDetail).toEqual(completed);
  expect(viewerResult).toEqual(result);
  expect(viewerEvidence).toEqual(evidence);
  expect(viewerDetail.result?.resultId).toBe(result.result.resultId);
  expect(viewerResult.result.resultId).toBe(result.result.resultId);
  expect(viewerEvidence.result?.resultId).toBe(result.result.resultId);
  expect(viewerEvidence.baseline.inspectionReportDigest).toBe(evidence.baseline.inspectionReportDigest);
  expect(viewerEvidence.current.inspectionReportDigest).toBe(evidence.current.inspectionReportDigest);

  const viewerDeniedCreate = await fetch(new URL(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/work-areas/${encodeURIComponent(fixture.workAreaId)}/analyses`,
    coreOrigin,
  ), {
    method: "POST",
    headers: {
      authorization: `Bearer ${viewerToken}`,
      "content-type": "application/json",
      "Idempotency-Key": `viewer-denied-${randomBytes(20).toString("hex")}`,
    },
    body: JSON.stringify({ baseline: fixture.baselineSelector, current: fixture.currentSelector }),
  });
  expect(viewerDeniedCreate.status, await viewerDeniedCreate.clone().text()).toBe(403);
  const viewerAnalysesAfter = await coreGet<{ items: AnalysisView[] }>(analysisCollection, viewerToken);
  expect(viewerAnalysesAfter.items.map((item) => item.analysisId)).toEqual(
    viewerAnalysesBefore.items.map((item) => item.analysisId),
  );
});

test("operator reuses three inspected epochs for two stored weekly Analysis results", async ({ page }) => {
  test.setTimeout(180_000);
  test.skip(scenario !== "weekly-reuse", "weekly reuse scenario only");
  const fixture = await readFixtureManifest(scenario);
  const thirdSelector = fixture.thirdSelector;
  if (thirdSelector === undefined) throw new Error("weekly inspection manifest lacks t2 selector");
  expect(fixture.inspectionReportDigests).toHaveLength(3);

  const operatorToken = await issueAccessToken("local-admin");
  const observations = await coreGet<{ items: ObservationOption[] }>(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/analysis-observations`,
    operatorToken,
  );
  const selectors = [fixture.baselineSelector, fixture.currentSelector, thirdSelector];
  const options = selectors.map((selector) => {
    const option = observations.items.find((item) => equalSelector(item.selector, selector));
    expect(option, `registered epoch for ${selector.workOrderId}`).toBeDefined();
    return option!;
  });
  expect(new Set(options.map((option) => option.observationEpochId)).size).toBe(3);

  await page.goto("/login");
  await page.getByRole("button", { name: "개발 Operations Console 시작" }).click();
  await expect(page).toHaveURL("http://localhost:3231/");
  await page.goto(`/sites/${encodeURIComponent(fixture.siteId)}/analysis`);
  await expect(page.getByRole("heading", { name: "현장 분석" })).toBeVisible();

  const workArea = page.getByLabel("작업구역");
  await expect(workArea.locator("option")).toHaveCount(2);
  await workArea.selectOption(fixture.workAreaId);

  async function selectEpoch(label: string, expected: ObservationOption): Promise<void> {
    const select = page.getByLabel(label);
    const labels = await select.locator("option").allTextContents();
    const index = labels.findIndex((text) => text.includes(expected.observationEpochId));
    expect(index, `${label} option for ${expected.observationEpochId}`).toBeGreaterThan(0);
    const value = await select.locator("option").nth(index).getAttribute("value");
    expect(value).not.toBeNull();
    await select.selectOption(value!);
  }

  async function submitPair(
    baseline: ObservationOption,
    current: ObservationOption,
  ): Promise<AnalysisView> {
    await selectEpoch("기준 관측", baseline);
    await selectEpoch("현재 관측", current);
    const postPromise = page.waitForResponse((response) =>
      response.request().method() === "POST"
        && response.url().includes(
          `/api/sites/${fixture.siteId}/work-areas/${fixture.workAreaId}/analyses`,
        ),
    );
    await page.getByRole("button", { name: "분석 요청" }).click();
    const submitted = await postPromise;
    const submittedBody = await submitted.text();
    expect(submitted.status(), submittedBody).toBe(202);
    const analysis = JSON.parse(submittedBody) as AnalysisView;
    expect(analysis.siteId).toBe(fixture.siteId);
    expect(analysis.workAreaId).toBe(fixture.workAreaId);
    expect(equalSelector(analysis.baseline, baseline.selector)).toBe(true);
    expect(equalSelector(analysis.current, current.selector)).toBe(true);
    expect(analysis.executionState).toBe("QUEUED");
    return analysis;
  }

  async function waitForCompleted(analysisId: string): Promise<AnalysisView> {
    const observed: { value?: AnalysisView } = {};
    await expect.poll(async () => {
      const detail = await coreGet<AnalysisView>(
        `/v1/sites/${fixture.siteId}/analyses/${analysisId}`,
        operatorToken,
      );
      observed.value = detail;
      return detail.executionState;
    }, { timeout: 60_000 }).toBe("COMPLETED");
    if (observed.value === undefined) throw new Error("worker completed without a Core detail view");
    return observed.value;
  }

  async function readStoredRecord(analysisId: string): Promise<{
    detail: AnalysisView;
    result: { analysisId: string; executionState: string; suitabilityState: string; result: AnalysisResult };
    evidence: AnalysisEvidence;
    v2Detail: AnalysisViewV2;
    v2Evidence: AnalysisEvidencePageV2;
  }> {
    const path = `/v1/sites/${fixture.siteId}/analyses/${analysisId}`;
    return {
      detail: await coreGet<AnalysisView>(path, operatorToken),
      result: await coreGet(
        `${path}/result`,
        operatorToken,
      ),
      evidence: await coreGet<AnalysisEvidence>(`${path}/evidence`, operatorToken),
      v2Detail: await coreGet<AnalysisViewV2>(
        `/v2/sites/${fixture.siteId}/analyses/${analysisId}`,
        operatorToken,
      ),
      v2Evidence: await coreGet<AnalysisEvidencePageV2>(
        `/v2/sites/${fixture.siteId}/analyses/${analysisId}/evidence?limit=32`,
        operatorToken,
      ),
    };
  }

  async function expectCardMatches(
    analysis: AnalysisView,
    record: Awaited<ReturnType<typeof readStoredRecord>>,
  ): Promise<void> {
    const card = page.getByRole("article").filter({ hasText: analysis.analysisId });
    expect(record.v2Detail.analysisId).toBe(record.detail.analysisId);
    expect(record.v2Detail.result?.resultId).toBe(record.result.result.resultId);
    expect(record.v2Detail.result?.metrics).toEqual(record.result.result.metrics);
    expect(record.v2Detail.result?.limitationCodes).toEqual(record.result.result.limitationCodes);
    expect(record.v2Evidence.analysisId).toBe(record.v2Detail.analysisId);
    expect(record.v2Evidence.evidenceRevision).toBe(record.v2Detail.evidenceRevision);
    expect(record.v2Evidence.evidenceDigest).toBe(record.v2Detail.evidenceDigest);
    await expect(card.getByText("실행 완료", { exact: true })).toBeVisible({ timeout: 30_000 });
    await card.getByRole("button", { name: "이 분석 보기" }).click();
    await expect(card).toContainText(record.result.result.resultId);
    await expect(card).toContainText("정확도 미확인");
    await expect(card).toContainText("정산 사용 승인을 뜻하지 않습니다.");
    await expect(card).toContainText(resultMetricLabel(record.result.result.metrics.cutM3));
    await expect(card).toContainText(resultMetricLabel(record.result.result.metrics.fillM3));
    await expect(card).toContainText(resultMetricLabel(record.result.result.metrics.netM3));
    await revealCoreDetails(card);
    for (const code of record.v2Detail.result?.limitationCodes ?? []) await expect(card).toContainText(code);
    await page.getByRole("button", { name: "근거 확인" }).click();
    const evidenceRegion = card.getByRole("region", { name: "근거" });
    await expect(evidenceRegion).toBeVisible();
    const baselineEvidence = await revealEpochEvidence(evidenceRegion, record.evidence.baseline.observationEpochId);
    const currentEvidence = await revealEpochEvidence(evidenceRegion, record.evidence.current.observationEpochId);
    await expect(baselineEvidence).toContainText(record.evidence.baseline.inspectionReportDigest);
    await expect(currentEvidence).toContainText(record.evidence.current.inspectionReportDigest);
    await expect(baselineEvidence).toContainText(record.evidence.baseline.inputDigest);
    await expect(currentEvidence).toContainText(record.evidence.current.inputDigest);
  }

  const firstAccepted = await submitPair(options[0], options[1]);
  const firstCompleted = await waitForCompleted(firstAccepted.analysisId);
  expect(firstCompleted.suitabilityState).toBe("PROVISIONAL_ACCURACY_UNVERIFIED");
  expect(firstCompleted.result).not.toBeNull();
  const firstRecord = await readStoredRecord(firstAccepted.analysisId);
  expect(firstRecord.detail).toEqual(firstCompleted);
  expect(firstRecord.result.analysisId).toBe(firstAccepted.analysisId);
  expect(firstRecord.result.executionState).toBe("COMPLETED");
  expect(firstRecord.result.suitabilityState).toBe("PROVISIONAL_ACCURACY_UNVERIFIED");
  expect(firstRecord.detail.result).toEqual(firstRecord.result.result);
  expect(firstRecord.evidence.result).toEqual(firstRecord.result.result);
  expect(firstRecord.evidence.analysisId).toBe(firstAccepted.analysisId);
  expect(firstRecord.evidence.baseline.selector).toEqual(fixture.baselineSelector);
  expect(firstRecord.evidence.current.selector).toEqual(fixture.currentSelector);
  expect(firstRecord.evidence.baseline.inspectionReportDigest).toBe(
    fixture.inspectionReportDigests[0],
  );
  expect(firstRecord.evidence.current.inspectionReportDigest).toBe(
    fixture.inspectionReportDigests[1],
  );
  expect(firstRecord.result.result.metrics.uncertaintyM3).toBeNull();

  const secondAccepted = await submitPair(options[1], options[2]);
  expect(secondAccepted.analysisId).not.toBe(firstAccepted.analysisId);
  const secondCompleted = await waitForCompleted(secondAccepted.analysisId);
  expect(secondCompleted.suitabilityState).toBe("PROVISIONAL_ACCURACY_UNVERIFIED");
  expect(secondCompleted.result).not.toBeNull();
  const secondRecord = await readStoredRecord(secondAccepted.analysisId);
  expect(secondRecord.detail).toEqual(secondCompleted);
  expect(secondRecord.result.analysisId).toBe(secondAccepted.analysisId);
  expect(secondRecord.result.executionState).toBe("COMPLETED");
  expect(secondRecord.result.suitabilityState).toBe("PROVISIONAL_ACCURACY_UNVERIFIED");
  expect(secondRecord.detail.result).toEqual(secondRecord.result.result);
  expect(secondRecord.evidence.result).toEqual(secondRecord.result.result);
  expect(secondRecord.evidence.analysisId).toBe(secondAccepted.analysisId);
  expect(secondRecord.evidence.baseline.selector).toEqual(fixture.currentSelector);
  expect(secondRecord.evidence.current.selector).toEqual(thirdSelector);
  expect(secondRecord.evidence.baseline.inspectionReportDigest).toBe(
    fixture.inspectionReportDigests[1],
  );
  expect(secondRecord.evidence.current.inspectionReportDigest).toBe(
    fixture.inspectionReportDigests[2],
  );
  expect(secondRecord.result.result.metrics.uncertaintyM3).toBeNull();

  expect(firstRecord.evidence.current.selector).toEqual(secondRecord.evidence.baseline.selector);
  expect(firstRecord.evidence.current.observedSha256).toBe(
    secondRecord.evidence.baseline.observedSha256,
  );
  expect(firstRecord.evidence.current.inputDigest).toBe(
    secondRecord.evidence.baseline.inputDigest,
  );
  expect(firstRecord.evidence.current.inspectionReportDigest).toBe(
    secondRecord.evidence.baseline.inspectionReportDigest,
  );
  expect(firstRecord.evidence.baseline.inputDigest).not.toBe(
    firstRecord.evidence.current.inputDigest,
  );
  expect(secondRecord.evidence.current.inputDigest).not.toBe(
    secondRecord.evidence.baseline.inputDigest,
  );
  expect(secondRecord.evidence.current.inputDigest).not.toBe(
    firstRecord.evidence.current.inputDigest,
  );
  expect(firstRecord.evidence.calculation.workAreaDefinitionDigest).toBe(
    secondRecord.evidence.calculation.workAreaDefinitionDigest,
  );
  expect(firstRecord.evidence.calculation.policy).toEqual(
    secondRecord.evidence.calculation.policy,
  );
  expect(firstRecord.evidence.calculation.runtime).toEqual(
    secondRecord.evidence.calculation.runtime,
  );
  for (const authorityField of [
    "assessmentRequestId",
    "admissionId",
    "admissionDigest",
    "calculationIdentityDigest",
    "calculationRequestId",
    "authorizationId",
  ]) {
    expect(firstRecord.detail.authority[authorityField]).not.toBe(
      secondRecord.detail.authority[authorityField],
    );
  }
  expect(firstRecord.evidence.calculation.calculationId).not.toBe(
    secondRecord.evidence.calculation.calculationId,
  );
  expect(firstRecord.result.result.resultId).not.toBe(secondRecord.result.result.resultId);
  expect(firstRecord.result.result.metrics.cutM3).toBeCloseTo(0.01, 6);
  expect(firstRecord.result.result.metrics.fillM3).toBeCloseTo(0.01, 6);
  expect(secondRecord.result.result.metrics.cutM3).toBeCloseTo(0.02, 6);
  expect(secondRecord.result.result.metrics.fillM3).toBeCloseTo(0.02, 6);

  const firstAfterSecond = await readStoredRecord(firstAccepted.analysisId);
  expect(firstAfterSecond).toEqual(firstRecord);
  await expectCardMatches(firstAccepted, firstAfterSecond);
  await expectCardMatches(secondAccepted, secondRecord);

  // Exercise the real page controls at their contract caps without creating
  // 51 worker jobs. The intercepted payloads are synthetic UI fixture rows;
  // the displayed weekly records remain sourced and checked from Core above.
  const v2List = await coreGet<AnalysisListPageV2>(
    `/v2/sites/${encodeURIComponent(fixture.siteId)}/analyses?limit=50`,
    operatorToken,
  );
  const firstRealItem = v2List.items.find((item) => item.analysisId === firstAccepted.analysisId);
  const secondRealItem = v2List.items.find((item) => item.analysisId === secondAccepted.analysisId);
  expect(firstRealItem).toBeDefined();
  expect(secondRealItem).toBeDefined();
  const fillerRows: AnalysisListItemV2[] = Array.from({ length: 48 }, (_, index) => ({
    analysisId: `analysis-pagination-fixture-${index + 1}`,
    siteId: fixture.siteId,
    workAreaId: fixture.workAreaId,
    executionState: "NOT_STARTED",
    suitabilityState: "BLOCKED",
    createdAt: new Date(Date.UTC(2026, 0, 1, 0, index)).toISOString(),
    resultId: null,
    metrics: null,
    limitationCount: 1,
    analysisHref: `/v2/sites/${fixture.siteId}/analyses/analysis-pagination-fixture-${index + 1}`,
  }));
  const pageTwoItem: AnalysisListItemV2 = {
    ...fillerRows[0]!,
    analysisId: "analysis-pagination-page-two",
    analysisHref: `/v2/sites/${fixture.siteId}/analyses/analysis-pagination-page-two`,
  };
  await page.route(`**/api/sites/${fixture.siteId}/analyses**`, async (route) => {
    const requestUrl = new URL(route.request().url());
    if (requestUrl.pathname !== `/api/sites/${fixture.siteId}/analyses`) return route.continue();
    const cursor = requestUrl.searchParams.get("cursor");
    const response = cursor === "synthetic-list-cursor"
      ? { siteId: fixture.siteId, items: [pageTwoItem], nextCursor: null }
      : { siteId: fixture.siteId, items: [firstRealItem!, secondRealItem!, ...fillerRows], nextCursor: "synthetic-list-cursor" };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
  });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("button", { name: "다음 분석 보기" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(50);
  await page.getByRole("button", { name: "다음 분석 보기" }).click();
  const pageTwoCard = page.getByRole("article").filter({ hasText: "analysis-pagination-page-two" });
  await expect(pageTwoCard).toContainText("차단됨");
  await expect(page.getByRole("button", { name: "다음 분석 보기" })).toHaveCount(0);
  await page.getByRole("article").filter({ hasText: firstAccepted.analysisId }).getByRole("button", { name: "이 분석 보기" }).click();
  await page.getByRole("article").filter({ hasText: secondAccepted.analysisId }).getByRole("button", { name: "이 분석 보기" }).click();

  const secondV2Detail = await coreGet<{ evidenceRevision: number; evidenceDigest: string }>(
    `/v2/sites/${encodeURIComponent(fixture.siteId)}/analyses/${encodeURIComponent(secondAccepted.analysisId)}`,
    operatorToken,
  );
  const actualEvidence = await coreGet<AnalysisEvidencePageV2>(
    `/v2/sites/${encodeURIComponent(fixture.siteId)}/analyses/${encodeURIComponent(secondAccepted.analysisId)}/evidence?limit=32`,
    operatorToken,
  );
  const evidenceFixtures: Array<Record<string, unknown>> = [
    ...actualEvidence.items,
    ...Array.from({ length: Math.max(0, 32 - actualEvidence.items.length) }, (_, index) => ({
      kind: "LIMITATION",
      recordId: `pagination-evidence-${index + 1}`,
      digest: `sha256:${(index + 1).toString(16).padStart(64, "0")}`,
      href: null,
      limitationCodes: [],
      source: "RESULT",
      code: `PAGINATION_FIXTURE_${index + 1}`,
      epoch: null,
      evidenceRef: null,
      detail: "synthetic pagination fixture",
    })),
  ].slice(0, 32);
  const evidencePageOne: AnalysisEvidencePageV2 = {
    analysisId: secondAccepted.analysisId,
    evidenceRevision: secondV2Detail.evidenceRevision,
    evidenceDigest: secondV2Detail.evidenceDigest,
    items: evidenceFixtures,
    nextCursor: "synthetic-evidence-cursor",
  };
  const evidencePageTwo: AnalysisEvidencePageV2 = {
    ...evidencePageOne,
    items: [{
      kind: "LIMITATION",
      recordId: "pagination-evidence-page-two",
      digest: `sha256:${"f".repeat(64)}`,
      href: null,
      limitationCodes: [],
      source: "RESULT",
      code: "PAGINATION_FIXTURE_PAGE_TWO",
      epoch: null,
      evidenceRef: null,
      detail: "synthetic second page",
    }],
    nextCursor: "synthetic-stale-evidence-cursor",
  };
  let evidenceCursorPageTwoRead = false;
  await page.route(
    `**/api/sites/${fixture.siteId}/analyses/${secondAccepted.analysisId}/evidence**`,
    async (route) => {
      const requestUrl = new URL(route.request().url());
      if (requestUrl.pathname !== `/api/sites/${fixture.siteId}/analyses/${secondAccepted.analysisId}/evidence`) return route.continue();
      const cursor = requestUrl.searchParams.get("cursor");
      if (cursor === "synthetic-evidence-cursor") {
        evidenceCursorPageTwoRead = true;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(evidencePageTwo) });
      } else if (cursor === "synthetic-stale-evidence-cursor") {
        await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "ANALYSIS_EVIDENCE_CURSOR_STALE" }) });
      } else {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(evidencePageOne) });
      }
    },
  );
  await page.getByRole("button", { name: "근거 확인" }).click();
  const evidenceRegion = page.getByRole("region", { name: "근거" });
  await expect(evidenceRegion).toContainText("현재 불러온 32개 항목");
  await page.getByRole("button", { name: "다음 근거 보기" }).click();
  const pageTwoEvidence = evidenceRegion.locator("details").last();
  await pageTwoEvidence.locator("summary").click();
  await expect(pageTwoEvidence).toContainText("pagination-evidence-page-two");
  expect(evidenceCursorPageTwoRead).toBe(true);
  await page.getByRole("button", { name: "다음 근거 보기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "근거 개정이 변경되었습니다." })).toBeVisible();
  await page.getByRole("button", { name: "근거 처음부터 다시 불러오기" }).click();
  await expect(evidenceRegion).toContainText("현재 불러온 32개 항목");
});

test("OIDC 사용자가 수직 기준 누락 관측의 분석 차단과 빈 worker queue를 확인한다", async ({ page }) => {
  test.setTimeout(120_000);
  test.skip(scenario !== "missing-vertical-reference", "spatial blocker scenario only");
  const fixture = await readFixtureManifest(scenario);
  expect(fixture.scenario).toBe(scenario);
  const operatorToken = await issueAccessToken("local-admin");
  const foreignToken = await issueAccessToken("local-empty-org-admin");
  const observations = await coreGet<{ items: ObservationOption[] }>(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/analysis-observations`,
    operatorToken,
  );
  const baselineOption = observations.items.find((item) => equalSelector(item.selector, fixture.baselineSelector));
  const currentOption = observations.items.find((item) => equalSelector(item.selector, fixture.currentSelector));
  expect(baselineOption).toBeDefined();
  expect(currentOption).toBeDefined();
  const foreignObservations = await fetch(new URL(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/analysis-observations`,
    coreOrigin,
  ), { headers: { authorization: `Bearer ${foreignToken}` } });
  expect(foreignObservations.status).toBe(404);

  await page.goto("/login");
  await page.getByRole("button", { name: "개발 Operations Console 시작" }).click();
  await expect(page).toHaveURL("http://localhost:3231/");
  await page.goto(`/sites/${encodeURIComponent(fixture.siteId)}/analysis`);
  await expect(page.getByRole("heading", { name: "현장 분석" })).toBeVisible();
  const workArea = page.getByLabel("작업구역");
  await expect(workArea.locator("option")).toHaveCount(2);
  await workArea.selectOption(fixture.workAreaId);
  for (const [label, expected] of [
    ["기준 관측", baselineOption!],
    ["현재 관측", currentOption!],
  ] as const) {
    const select = page.getByLabel(label);
    const options = await select.locator("option").allTextContents();
    const index = options.findIndex((text) => text.includes(expected.observationEpochId));
    expect(index, `${label} option for ${expected.observationEpochId}`).toBeGreaterThan(0);
    const value = await select.locator("option").nth(index).getAttribute("value");
    expect(value).not.toBeNull();
    await select.selectOption(value!);
  }

  const postPromise = page.waitForResponse((response) =>
    response.request().method() === "POST"
      && response.url().includes(`/api/sites/${fixture.siteId}/work-areas/${fixture.workAreaId}/analyses`),
  );
  await page.getByRole("button", { name: "분석 요청" }).click();
  const submitted = await postPromise;
  expect(submitted.status()).toBe(202);
  const blocked = await submitted.json() as AnalysisView;
  expect(blocked.siteId).toBe(fixture.siteId);
  expect(blocked.workAreaId).toBe(fixture.workAreaId);
  expect(equalSelector(blocked.baseline, fixture.baselineSelector)).toBe(true);
  expect(equalSelector(blocked.current, fixture.currentSelector)).toBe(true);
  expect(blocked.executionState).toBe("NOT_STARTED");
  expect(blocked.suitabilityState).toBe("BLOCKED");
  expect(blocked.result).toBeNull();
  expect(blocked.blockers.map((item) => item.code)).toContain("ESSENTIAL_INPUT_UNAVAILABLE");

  const detailPath = `/v1/sites/${fixture.siteId}/analyses/${blocked.analysisId}`;
  const detail = await coreGet<AnalysisView>(detailPath, operatorToken);
  const resultView = await coreGet<{
    executionState: string;
    suitabilityState: string;
    result: AnalysisResult | null;
    blockers: { code: string }[];
  }>(`${detailPath}/result`, operatorToken);
  const evidence = await coreGet<AnalysisEvidence>(`${detailPath}/evidence`, operatorToken);
  expect(detail.analysisId).toBe(blocked.analysisId);
  expect(detail.executionState).toBe("NOT_STARTED");
  expect(detail.suitabilityState).toBe("BLOCKED");
  expect(detail.result).toBeNull();
  expect(detail.blockers.map((item) => item.code)).toContain("ESSENTIAL_INPUT_UNAVAILABLE");
  expect(resultView).toMatchObject({
    executionState: "NOT_STARTED",
    suitabilityState: "BLOCKED",
    result: null,
  });
  expect(resultView.blockers.map((item) => item.code)).toContain("ESSENTIAL_INPUT_UNAVAILABLE");
  expect(evidence.analysisId).toBe(blocked.analysisId);
  expect(evidence.result).toBeNull();
  for (const suffix of ["", "/result", "/evidence"]) {
    const foreignAnalysis = await fetch(new URL(`${detailPath}${suffix}`, coreOrigin), {
      headers: { authorization: `Bearer ${foreignToken}` },
    });
    expect(foreignAnalysis.status, `foreign organization ${suffix || "detail"}`).toBe(404);
  }

  const card = page.getByRole("article").filter({ hasText: blocked.analysisId });
  await expect(card.getByText("시작 전", { exact: true })).toBeVisible();
  await expect(card.getByText("차단됨", { exact: true })).toBeVisible();
  await revealCoreDetails(card);
  await expect(card).toContainText("ESSENTIAL_INPUT_UNAVAILABLE");
  await expect(card).not.toContainText("절토");
  await expect(card).not.toContainText("성토");
  await expect(card).not.toContainText("순변화");

  const emptyQueue = await requestRunnerControl("CHECK_NO_WORKER_JOB");
  expect(emptyQueue).toEqual({
    controlId: emptyQueue.controlId,
    status: "CHECKED",
    pendingJobCount: 0,
  });
});

test("실제 검사된 겹치는 NoData DSM 분석이 worker에서 차단되고 결과를 발행하지 않는다", async ({ page }) => {
  test.setTimeout(120_000);
  test.skip(scenario !== "overlapping-current-nodata-cell", "overlapping NoData scenario only");
  const fixture = await readFixtureManifest(scenario);
  expect(fixture.scenario).toBe(scenario);
  const operatorToken = await issueAccessToken("local-admin");
  const foreignToken = await issueAccessToken("local-empty-org-admin");
  const observations = await coreGet<{ items: ObservationOption[] }>(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/analysis-observations`,
    operatorToken,
  );
  const baselineOption = observations.items.find((item) => equalSelector(item.selector, fixture.baselineSelector));
  const currentOption = observations.items.find((item) => equalSelector(item.selector, fixture.currentSelector));
  expect(baselineOption).toBeDefined();
  expect(currentOption).toBeDefined();
  const foreignObservations = await fetch(new URL(
    `/v1/sites/${encodeURIComponent(fixture.siteId)}/analysis-observations`,
    coreOrigin,
  ), { headers: { authorization: `Bearer ${foreignToken}` } });
  expect(foreignObservations.status).toBe(404);

  await page.goto("/login");
  await page.getByRole("button", { name: "개발 Operations Console 시작" }).click();
  await expect(page).toHaveURL("http://localhost:3231/");
  await page.goto(`/sites/${encodeURIComponent(fixture.siteId)}/analysis`);
  await expect(page.getByRole("heading", { name: "현장 분석" })).toBeVisible();
  const workArea = page.getByLabel("작업구역");
  await expect(workArea.locator("option")).toHaveCount(2);
  await workArea.selectOption(fixture.workAreaId);
  for (const [label, expected] of [
    ["기준 관측", baselineOption!],
    ["현재 관측", currentOption!],
  ] as const) {
    const select = page.getByLabel(label);
    const options = await select.locator("option").allTextContents();
    const index = options.findIndex((text) => text.includes(expected.observationEpochId));
    expect(index, `${label} option for ${expected.observationEpochId}`).toBeGreaterThan(0);
    const value = await select.locator("option").nth(index).getAttribute("value");
    expect(value).not.toBeNull();
    await select.selectOption(value!);
  }

  const postPromise = page.waitForResponse((response) =>
    response.request().method() === "POST"
      && response.url().includes(`/api/sites/${fixture.siteId}/work-areas/${fixture.workAreaId}/analyses`),
  );
  await page.getByRole("button", { name: "분석 요청" }).click();
  const submitted = await postPromise;
  expect(submitted.status()).toBe(202);
  const queued = await submitted.json() as AnalysisView;
  expect(queued.siteId).toBe(fixture.siteId);
  expect(queued.workAreaId).toBe(fixture.workAreaId);
  expect(equalSelector(queued.baseline, fixture.baselineSelector)).toBe(true);
  expect(equalSelector(queued.current, fixture.currentSelector)).toBe(true);
  expect(queued.executionState).toBe("QUEUED");

  const detailPath = `/v1/sites/${fixture.siteId}/analyses/${queued.analysisId}`;
  const terminalObservation: { detail?: AnalysisView } = {};
  await expect.poll(async () => {
    const currentDetail = await coreGet<AnalysisView>(detailPath, operatorToken);
    terminalObservation.detail = currentDetail;
    return currentDetail.executionState;
  }, { timeout: 60_000 }).toBe("FAILED");
  const detail = terminalObservation.detail;
  if (detail === undefined) throw new Error("failed analysis detail was not observed");
  expect(detail.suitabilityState).toBe("BLOCKED");
  expect(detail.result).toBeNull();
  expect(detail.blockers.map((item) => item.code)).toEqual([
    "INSUFFICIENT_COMMON_VALID_COVERAGE",
  ]);

  const resultView = await coreGet<{
    analysisId: string;
    executionState: string;
    suitabilityState: string;
    result: AnalysisResult | null;
    blockers: { code: string }[];
  }>(`${detailPath}/result`, operatorToken);
  const evidence = await coreGet<AnalysisEvidence>(`${detailPath}/evidence`, operatorToken);
  expect(resultView).toMatchObject({
    analysisId: queued.analysisId,
    executionState: "FAILED",
    suitabilityState: "BLOCKED",
    result: null,
  });
  expect(resultView.blockers.map((item) => item.code)).toEqual([
    "INSUFFICIENT_COMMON_VALID_COVERAGE",
  ]);
  expect(evidence.analysisId).toBe(queued.analysisId);
  expect(evidence.result).toBeNull();
  expect(evidence.baseline.selector).toEqual(fixture.baselineSelector);
  expect(evidence.current.selector).toEqual(fixture.currentSelector);
  expect(evidence.baseline.inspectionReportDigest).toBe(fixture.inspectionReportDigests[0]);
  expect(evidence.current.inspectionReportDigest).toBe(fixture.inspectionReportDigests[1]);
  expect(evidence.baseline.observedSha256).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(evidence.current.observedSha256).toMatch(/^sha256:[0-9a-f]{64}$/);

  const stableDetail = await coreGet<AnalysisView>(detailPath, operatorToken);
  const stableResult = await coreGet<typeof resultView>(`${detailPath}/result`, operatorToken);
  const stableEvidence = await coreGet<AnalysisEvidence>(`${detailPath}/evidence`, operatorToken);
  expect(stableDetail).toEqual(detail);
  expect(stableResult).toEqual(resultView);
  expect(stableEvidence).toEqual(evidence);

  for (const suffix of ["", "/result", "/evidence"]) {
    const foreignAnalysis = await fetch(new URL(`${detailPath}${suffix}`, coreOrigin), {
      headers: { authorization: `Bearer ${foreignToken}` },
    });
    expect(foreignAnalysis.status, `foreign organization ${suffix || "detail"}`).toBe(404);
  }

  const card = page.getByRole("article").filter({ hasText: queued.analysisId });
  await expect(card.getByText("실패", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(card.getByText("차단됨", { exact: true })).toBeVisible();
  await revealCoreDetails(card);
  await expect(card).toContainText("INSUFFICIENT_COMMON_VALID_COVERAGE");
  await expect(card).not.toContainText("절토");
  await expect(card).not.toContainText("성토");
  await expect(card).not.toContainText("순변화");

  const emptyQueue = await requestRunnerControl("CHECK_NO_WORKER_JOB");
  expect(emptyQueue).toEqual({
    controlId: emptyQueue.controlId,
    status: "CHECKED",
    pendingJobCount: 0,
  });
});
