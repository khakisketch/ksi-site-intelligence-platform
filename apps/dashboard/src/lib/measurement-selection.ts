/**
 * 어떤 단면 결과를 기준·현재로 보여 줄지 정하는 규칙. 서버 컴포넌트가 쓰는 순수 함수다.
 *
 * - 선 모양(lineDigest)이 같은 결과만 한 화면에 섞는다. 다른 개정의 결과는 개수만 알린다.
 * - 촬영 날짜를 모르는 자료는 순서를 매기지 않고 뒤에 둔다. 날짜를 짐작하지 않는다.
 * - 선택만으로 새 요청을 만들지 않는다. 이미 있는 결과 가운데서만 고른다.
 */
import type { MeasurementFeatureRevision, SurfaceProfileJobView } from "@/lib/core-api/measurement-types";

const SEOUL_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" });
const CALENDAR_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** 자료의 촬영 날짜(YYYY-MM-DD). 달력 날짜가 있으면 그대로, 없으면 촬영 시작 시각의 서울 날짜. 없으면 null. */
export function captureDateLabel(asset: { captureDate?: string | null; captureStartedAt?: string | null }): string | null {
  if (asset.captureDate && CALENDAR_DATE.test(asset.captureDate) && !Number.isNaN(Date.parse(asset.captureDate))) return asset.captureDate;
  if (asset.captureStartedAt) {
    const parsed = Date.parse(asset.captureStartedAt);
    if (!Number.isNaN(parsed)) return SEOUL_DATE.format(parsed);
  }
  return null;
}

export interface DateLabel {
  label: string;
  /** 정렬에 쓰는 날짜. 모르면 null. */
  date: string | null;
}

export interface ProfileDateOption {
  jobId: string;
  assetRef: string;
  label: string;
  date: string | null;
  availability: SurfaceProfileJobView["availability"];
}

export interface ProfileFailure {
  label: string;
  reason: string | null;
}

export interface ProfileChoice {
  options: ProfileDateOption[];
  refJobId: string | null;
  curJobId: string | null;
  otherRevisionCount: number;
  failures: ProfileFailure[];
  pendingCount: number;
}

const newestFirst = (a: SurfaceProfileJobView, b: SurfaceProfileJobView) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0);

export function chooseProfileJobs(input: {
  jobs: readonly SurfaceProfileJobView[];
  feature: MeasurementFeatureRevision;
  labelOf: (assetRef: string) => DateLabel;
  requestedRef?: string;
  requestedCur?: string;
}): ProfileChoice {
  const { feature, labelOf } = input;
  const sameLine = input.jobs.filter((job) => job.feature.featureId === feature.featureId);
  const exact = sameLine.filter((job) => job.feature.lineDigest === feature.lineDigest).sort(newestFirst);
  const otherRevisionCount = sameLine.length - exact.length;

  const completed = new Map<string, SurfaceProfileJobView>();
  for (const job of exact) {
    if (job.executionState === "COMPLETED" && !completed.has(job.assetRef)) completed.set(job.assetRef, job);
  }
  const failedByAsset = new Map<string, SurfaceProfileJobView>();
  let pendingCount = 0;
  for (const job of exact) {
    if (job.executionState === "QUEUED" || job.executionState === "RUNNING") pendingCount += 1;
    if (job.executionState === "FAILED" && !completed.has(job.assetRef) && !failedByAsset.has(job.assetRef)) failedByAsset.set(job.assetRef, job);
  }

  const options: ProfileDateOption[] = [...completed.values()].map((job) => {
    const { label, date } = labelOf(job.assetRef);
    return { jobId: job.jobId, assetRef: job.assetRef, label, date, availability: job.availability };
  });
  // 같은 날짜가 겹치면 자료 참조 끝자리로 구분한다.
  const seen = new Map<string, number>();
  for (const option of options) seen.set(option.label, (seen.get(option.label) ?? 0) + 1);
  for (const option of options) {
    if ((seen.get(option.label) ?? 0) > 1) option.label = `${option.label} · #${option.assetRef.slice(-4)}`;
  }
  options.sort((a, b) => {
    if (a.date === null && b.date === null) return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
    if (a.date === null) return 1;
    if (b.date === null) return -1;
    return a.date < b.date ? -1 : a.date > b.date ? 1 : a.label < b.label ? -1 : 1;
  });

  const ids = new Set(options.map((option) => option.jobId));
  const known = options.filter((option) => option.date !== null);
  const latest = (known.length > 0 ? known[known.length - 1] : options[options.length - 1]) ?? null;
  const curJobId = input.requestedCur && ids.has(input.requestedCur) ? input.requestedCur : latest?.jobId ?? null;
  let refJobId: string | null;
  if (input.requestedRef === "") refJobId = null;
  else if (input.requestedRef && ids.has(input.requestedRef)) refJobId = input.requestedRef;
  else {
    const earliest = (known.length > 0 ? known : options).find((option) => option.jobId !== curJobId) ?? null;
    refJobId = earliest?.jobId ?? null;
  }

  const failures: ProfileFailure[] = [...failedByAsset.values()].map((job) => ({ label: labelOf(job.assetRef).label, reason: job.reason }));
  return { options, refJobId, curJobId, otherRevisionCount, failures, pendingCount };
}
