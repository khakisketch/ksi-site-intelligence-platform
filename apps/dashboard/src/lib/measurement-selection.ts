/**
 * 어떤 단면 결과를 기준·현재로 보여 줄지 정하는 규칙. 서버 컴포넌트가 쓰는 순수 함수다.
 *
 * - 선택한 선 ID·개정·모양이 모두 같은 결과만 한 화면에 섞는다. 다른 개정의 결과는 개수만 알린다.
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
  /** 선택 자료에서 단면으로 이어진 경우 현재 자료를 고정한다. */
  sourceAssetRef?: string;
  requestedRef?: string;
  requestedCur?: string;
}): ProfileChoice {
  const { feature, labelOf } = input;
  const sameLine = input.jobs.filter((job) => job.feature.featureId === feature.featureId);
  const exact = sameLine.filter((job) => job.feature.revision === feature.revision && job.feature.lineDigest === feature.lineDigest).sort(newestFirst);
  const otherRevisionCount = sameLine.length - exact.length;

  const requestedSourceCurrent = input.sourceAssetRef && input.requestedCur !== undefined
    ? exact.find((job) => job.jobId === input.requestedCur
      && job.assetRef === input.sourceAssetRef
      && job.executionState === "COMPLETED") ?? null
    : null;
  const requestedSourceBaseline = input.sourceAssetRef && input.requestedRef
    ? exact.find((job) => job.jobId === input.requestedRef && job.assetRef !== input.sourceAssetRef)
    : null;
  const requestedIds = new Set(
    input.sourceAssetRef
      ? [requestedSourceCurrent?.jobId, requestedSourceBaseline?.jobId].filter((id): id is string => Boolean(id))
      : [input.requestedRef, input.requestedCur].filter((id): id is string => Boolean(id)),
  );
  const completed = new Map<string, SurfaceProfileJobView>();
  for (const job of exact) {
    if (job.executionState !== "COMPLETED") continue;
    const chosen = completed.get(job.assetRef);
    if (!chosen || (requestedIds.has(job.jobId) && !requestedIds.has(chosen.jobId))) completed.set(job.assetRef, job);
  }
  const failedByAsset = new Map<string, SurfaceProfileJobView>();
  let pendingCount = 0;
  for (const job of exact) {
    const relevantToSource = !input.sourceAssetRef
      || job.assetRef === input.sourceAssetRef
      || job.assetRef === requestedSourceBaseline?.assetRef;
    if (relevantToSource && (job.executionState === "QUEUED" || job.executionState === "RUNNING")) pendingCount += 1;
    if (job.executionState === "FAILED" && !completed.has(job.assetRef) && !failedByAsset.has(job.assetRef)) failedByAsset.set(job.assetRef, job);
  }

  const completedOptions: ProfileDateOption[] = [...completed.values()].map((job) => {
    const { label, date } = labelOf(job.assetRef);
    return { jobId: job.jobId, assetRef: job.assetRef, label, date, availability: job.availability };
  });
  // 같은 날짜가 겹치면 자료 참조 끝자리로 구분한다.
  const seen = new Map<string, number>();
  for (const option of completedOptions) seen.set(option.label, (seen.get(option.label) ?? 0) + 1);
  for (const option of completedOptions) {
    if ((seen.get(option.label) ?? 0) > 1) option.label = `${option.label} · #${option.assetRef.slice(-4)}`;
  }
  const selectedInFlight = exact
    .filter((job) => requestedIds.has(job.jobId) && job.executionState !== "COMPLETED")
    .map((job) => {
      const { label, date } = labelOf(job.assetRef);
      const state = job.executionState === "QUEUED" || job.executionState === "RUNNING"
        ? "단면 처리 중"
        : job.executionState === "FAILED" ? "단면 실패" : "단면 취소";
      return {
        jobId: job.jobId,
        assetRef: job.assetRef,
        label: `${label} · ${state} · #${job.assetRef.slice(-4)}`,
        date,
        availability: job.availability,
      };
    });
  const sortByDate = (a: ProfileDateOption, b: ProfileDateOption) => {
    if (a.date === null && b.date === null) return a.label < b.label ? -1 : a.label > b.label ? 1 : 0;
    if (a.date === null) return 1;
    if (b.date === null) return -1;
    return a.date < b.date ? -1 : a.date > b.date ? 1 : a.label < b.label ? -1 : 1;
  };
  completedOptions.sort(sortByDate);
  const options = [...completedOptions, ...selectedInFlight];
  options.sort(sortByDate);

  const ids = new Set(options.map((option) => option.jobId));
  const known = completedOptions.filter((option) => option.date !== null);
  const latest = (known.length > 0 ? known[known.length - 1] : completedOptions[completedOptions.length - 1]) ?? null;
  if (input.sourceAssetRef) {
    const invalidRequestedCurrent = input.requestedCur !== undefined && requestedSourceCurrent === null;
    const sourceCurrent = requestedSourceCurrent
      ? completedOptions.find((option) => option.jobId === requestedSourceCurrent.jobId) ?? null
      : completedOptions.find((option) => option.assetRef === input.sourceAssetRef) ?? null;
    const curJobId = sourceCurrent?.jobId ?? null;
    const requestedBaseline = !invalidRequestedCurrent && input.requestedRef
      ? options.find((option) => option.jobId === requestedSourceBaseline?.jobId
        && option.jobId !== curJobId
        && option.assetRef !== input.sourceAssetRef)
      : null;
    const visibleAssets = new Set([
      input.sourceAssetRef,
      invalidRequestedCurrent ? undefined : requestedSourceBaseline?.assetRef,
    ].filter((ref): ref is string => Boolean(ref)));
    return {
      options,
      refJobId: curJobId && !invalidRequestedCurrent ? requestedBaseline?.jobId ?? null : null,
      curJobId: invalidRequestedCurrent ? null : curJobId,
      otherRevisionCount,
      failures: [...failedByAsset.values()]
        .filter((job) => visibleAssets.has(job.assetRef))
        .map((job) => ({ label: labelOf(job.assetRef).label, reason: job.reason })),
      pendingCount: exact.filter((job) => visibleAssets.has(job.assetRef)
        && (job.executionState === "QUEUED" || job.executionState === "RUNNING")).length,
    };
  }

  const curJobId = input.requestedCur && ids.has(input.requestedCur) ? input.requestedCur : latest?.jobId ?? null;
  let refJobId: string | null;
  if (input.requestedRef === "") refJobId = null;
  else if (input.requestedRef && ids.has(input.requestedRef)) refJobId = input.requestedRef;
  else {
    const defaultOptions = known.length > 0 ? known : completedOptions;
    const earliest = defaultOptions.find((option) => option.jobId !== curJobId) ?? null;
    refJobId = earliest?.jobId ?? null;
  }

  const failures: ProfileFailure[] = [...failedByAsset.values()].map((job) => ({ label: labelOf(job.assetRef).label, reason: job.reason }));
  return { options, refJobId, curJobId, otherRevisionCount, failures, pendingCount };
}
