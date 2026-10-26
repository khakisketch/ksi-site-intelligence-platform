import Link from "next/link";
import { notFound } from "next/navigation";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import {
  getSpatialDataRequest,
  isSpatialDataAvailability,
  isSpatialDataExecutionState,
  listSpatialDataRequests,
  type SpatialDataAvailability,
  type SpatialDataExecutionState,
  type SpatialDataJobView,
  type SpatialDataReceipt,
} from "@/lib/core-api/spatial-data-requests";
import { getSite } from "@/lib/core-api/sites";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { listSpatialAssets } from "@/lib/core-api/spatial-assets";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatCountKo, formatNumberKo } from "@/lib/number-format";
import {
  requestRowPresentations,
  type CatalogAssetInfo,
} from "@/lib/human-labels";
import {
  capturePeriodTitle,
  dataKindLabel,
  dataRequestTitle,
  isSupportedDataKind,
} from "@/lib/operator-language";

import { SpatialDataRequestActions } from "./SpatialDataRequestActions";
import { SpatialDataReceiptPreview } from "./SpatialDataReceiptPreview";
import { WorkAreaHistorySelect } from "./WorkAreaHistorySelect";

export const metadata = { title: "구역 자료 준비 · KSI" };

type SearchValue = string | string[] | undefined;
type SearchParams = { workAreaId?: SearchValue; cursor?: SearchValue; requestId?: SearchValue; assetRef?: SearchValue };

const REQUEST_ID_PATTERN = /^sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ASSET_REF_PATTERN = /^ksa-v1-[0-9a-f]{64}$/;
const ACTIVE_STATES: readonly SpatialDataExecutionState[] = ["QUEUED", "RUNNING"];
const READ_PERMISSION_MESSAGE = "이 현장의 구역 자료 준비 기록을 볼 권한이 없습니다. 현장 담당자에게 접근 권한을 요청하세요.";

const STATE_PRESENTATION: Record<SpatialDataExecutionState, { label: string; tone: "neutral" | "progress" | "caution" | "positive" | "warning" }> = {
  QUEUED: { label: "대기", tone: "progress" },
  RUNNING: { label: "처리 중", tone: "progress" },
  COMPLETED: { label: "완료", tone: "positive" },
  FAILED: { label: "실패", tone: "warning" },
  CANCELED: { label: "취소됨", tone: "neutral" },
  EXPIRED: { label: "기한 만료", tone: "caution" },
};

const AVAILABILITY_LABEL: Record<SpatialDataAvailability, string> = {
  NOT_READY: "아직 준비되지 않음",
  AVAILABLE: "파일 접근 허용",
  ACCESS_REVOKED: "접근 회수됨",
  ACCESS_EXPIRED: "접근 기한 만료",
  RETENTION_EXPIRED: "보관 기한 만료",
  UNAVAILABLE: "현재 접근 불가",
};

function singleQueryValue(value: SearchValue): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function pageHref(siteId: string, workAreaId: string, values: { cursor?: string; requestId?: string } = {}): string {
  const query = new URLSearchParams({ workAreaId });
  if (values.cursor) query.set("cursor", values.cursor);
  if (values.requestId) query.set("requestId", values.requestId);
  return `/sites/${encodeURIComponent(siteId)}/spatial-data-requests?${query.toString()}`;
}

function stateBadge(state: SpatialDataExecutionState) {
  const presentation = STATE_PRESENTATION[state];
  return <StateBadge label={presentation.label} tone={presentation.tone} />;
}

function availabilityText(availability: SpatialDataAvailability) {
  return <span className="text-[11.5px] text-ink-2">{AVAILABILITY_LABEL[availability]}</span>;
}

function errorView(error: unknown, scope: "areas" | "list" | "detail", siteId: string) {
  if (error instanceof CoreApiError) {
    if (error.status === 404) {
      if (scope === "areas") {
        return <ErrorState message="작업구역 목록을 확인할 수 없습니다." tone="high" action={{ label: "현장으로 돌아가기", href: `/sites/${encodeURIComponent(siteId)}` }} />;
      }
      return <ErrorState
        message={scope === "list" ? "작업구역을 확인할 수 없거나 요청 목록을 조회할 수 없습니다." : "요청을 찾을 수 없거나 현재 조회할 수 없습니다."}
        tone="high"
        action={{ label: "구역을 다시 선택", href: `/sites/${encodeURIComponent(siteId)}/spatial-data-requests` }}
      />;
    }
    if (error.status === 403) {
      return <ErrorState message={READ_PERMISSION_MESSAGE} tone="high" />;
    }
    if (error.status === 503 || error.status >= 500) {
      return <ErrorState message="구역 자료 준비 기록을 일시적으로 불러오지 못했습니다." retryable retryAfterSeconds={error.retryAfterSeconds} />;
    }
    return <ErrorState message="요청 정보를 확인할 수 없습니다." tone="high" />;
  }
  return <ErrorState message="구역 자료 준비 정보를 불러오지 못했습니다." retryable />;
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="min-w-0">
    <dt className="text-[11px] text-ink-muted">{label}</dt>
    <dd className={`mt-0.5 break-words text-[12.5px] text-ink-2 ${mono ? "font-mono text-[11px]" : ""}`}>{value}</dd>
  </div>;
}

function formatTuple(values: readonly number[] | undefined): string {
  if (!values || values.some((value) => !Number.isFinite(value))) return "등록된 범위 값의 형식을 확인할 수 없음";
  return `[${values.map((value) => formatNumberKo(value, 4)).join(", ")}]`;
}

function exactBytes(value: number): string {
  return Number.isSafeInteger(value) && value >= 0 ? formatBytesKo(value) : "정확한 크기 표시 불가";
}

function ReceiptFacts({ receipt }: { receipt: SpatialDataReceipt }) {
  return <section className="border-t border-line pt-4">
    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line pb-3">
      <div>
        <h3 className="text-[15px] font-bold">준비된 출력 정보</h3>
        <p className="mt-1 text-[11.5px] text-ink-muted">COMPLETED 요청의 출력·공간 사실. 이 출력 정보는 정확도 평가나 현장 적합성 판정이 아닙니다.</p>
      </div>
      {receipt.receiptDigest && <span className="max-w-full break-all font-mono text-[10.5px] text-ink-muted">출력 정보 {receipt.receiptDigest}</span>}
    </div>
    <dl className="mt-4 grid gap-x-5 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
      <Fact label="산출물 종류" value={receipt.artifactKind} mono />
      <Fact label="출력 크기" value={exactBytes(receipt.outputSizeBytes)} />
      <Fact label="출력 파일 확인값(SHA-256)" value={receipt.outputSha256} mono />
      <Fact label="픽셀 창(파일 좌표 순서)" value={formatTuple(receipt.pixelWindow)} mono />
      <Fact label="출력 픽셀 크기" value={`${formatCountKo(receipt.width)} × ${formatCountKo(receipt.height)} pixels`} />
      <Fact label="실제 범위(파일 좌표 순서)" value={formatTuple(receipt.actualBounds)} mono />
      <Fact label="요청 범위(파일 좌표 순서)" value={formatTuple(receipt.requestedBounds)} mono />
      <Fact label="관측 좌표 기준" value={receipt.observedCrsIdentifier} mono />
      <Fact label="관측 좌표 기준 확인값" value={receipt.observedCrsDigest} mono />
      <Fact label="준비 시각" value={formatKoreanDateTime(receipt.preparedAt, { dateStyle: "medium", timeStyle: "short" })} />
      <Fact label="정확도 평가" value="수행하지 않음 (accuracyAssessed=false)" />
    </dl>
    <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
      <div><p className="text-[11px] text-ink-muted">Attribution</p><p className="mt-1 break-words text-[12.5px] leading-5 text-ink-2">{receipt.attribution}</p></div>
      <div><p className="text-[11px] text-ink-muted">Modification notice</p><p className="mt-1 break-words text-[12.5px] leading-5 text-ink-2">{receipt.modificationNotice}</p></div>
    </div>
    <div className="mt-3 rounded-md border border-high/30 bg-high-bg px-3 py-2 text-[11.5px] leading-5 text-high-ink">
      <p className="font-semibold">해석 범위</p>
      <p className="mt-0.5">파일 준비와 출력 정보 기록은 좌표 기준의 현장 정확도, 측량·정산 적합성 또는 분석 적격성을 보증하지 않습니다.</p>
      {receipt.limitations.length > 0 && <ul className="mt-1 list-disc pl-5">{receipt.limitations.map((limitation, index) => <li key={`${index}-${limitation}`} className="break-words">{limitation}</li>)}</ul>}
    </div>
  </section>;
}

function RequestDetail({
  item,
  siteId,
  workAreaName,
  assetInfo,
  canCancel,
  backHref,
}: {
  item: SpatialDataJobView;
  siteId: string;
  workAreaName: string;
  assetInfo: CatalogAssetInfo | null;
  canCancel: boolean;
  backHref: string;
}) {
  const isCompleted = item.executionState === "COMPLETED";
  const hasReceipt = isCompleted && item.receipt != null && item.receipt.jobId === item.jobId;
  const active = ACTIVE_STATES.includes(item.executionState);
  const fileHref = `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(item.workAreaId)}/spatial-data-requests/${encodeURIComponent(item.jobId)}/file`;

  return <section className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4 sm:p-5">
    <header className="flex flex-col gap-3 border-b border-line pb-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">선택한 요청</p>
        <h2 className="mt-1 text-[16px] font-bold tracking-tight break-keep">{dataRequestTitle(item.createdAt)}</h2>
        <p className="mt-1 text-[12.5px] text-ink-2">{workAreaName} · {formatKoreanDateTime(item.createdAt, { dateStyle: "medium", timeStyle: "short" })} 요청 기록 생성</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">{stateBadge(item.executionState)}{availabilityText(item.availability)}</div>
    </header>
    <section aria-label="원본 자료" className="rounded-lg border border-line bg-sunk/50 px-3 py-2">
      <h3 className="text-[12.5px] font-bold">원본 자료</h3>
      {assetInfo
        ? <p className="mt-1 break-words text-[12.5px] leading-5 text-ink-2">{dataKindLabel(assetInfo.kind)} · {capturePeriodTitle(assetInfo.captureStartedAt ?? null, assetInfo.captureEndedAt ?? null)} · {workAreaName}</p>
        : <p className="mt-1 text-[12px] leading-5 text-ink-2">원본 정보를 확인하지 못했습니다. 현재 조회한 카탈로그에서 확인되지 않아 표시만 생략합니다. 원본이 삭제됐다는 뜻이 아닙니다.</p>}
      <details className="mt-1 text-[12px] text-ink-2">
        <summary className="tap-target cursor-pointer font-semibold text-ink-muted">원본 처리 상세 보기</summary>
        {assetInfo && <p className="mt-1 break-words border-l-2 border-line pl-2">원본 파일명 · {assetInfo.fileName}</p>}
        {assetInfo && !isSupportedDataKind(assetInfo.kind) && <p className="mt-1 break-all border-l-2 border-line pl-2">원본 종류(원문) · {assetInfo.kind}</p>}
        <p className="mt-1 break-all border-l-2 border-line pl-2">원본 assetRef · {item.assetRef}</p>
      </details>
      <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">{hasReceipt
        ? "요청 범위는 아래 준비된 출력 정보에 기록된 값(요청 범위·실제 범위)으로 확인하세요."
        : "출력 정보가 없어 요청 범위를 표시하지 않습니다. 원본이 없다는 뜻이 아닙니다."}</p>
    </section>
    <details className="text-[12px] text-ink-2">
      <summary className="tap-target cursor-pointer font-semibold text-ink-muted">처리 상세</summary>
      <dl className="mt-1 grid gap-2 border-l-2 border-line pl-3 sm:grid-cols-2">
        <div className="min-w-0"><dt className="text-[11px] text-ink-muted">요청 ID</dt><dd className="break-all font-mono text-[11px]">{item.jobId}</dd></div>
        <div className="min-w-0"><dt className="text-[11px] text-ink-muted">Site / WorkArea</dt><dd className="break-all font-mono text-[11px]">{item.siteId} / {item.workAreaId}</dd></div>
        <div className="min-w-0"><dt className="text-[11px] text-ink-muted">Core 실행 상태</dt><dd className="break-all font-mono text-[11px]">{item.executionState}</dd></div>
        <div className="min-w-0"><dt className="text-[11px] text-ink-muted">Core availability</dt><dd className="break-all font-mono text-[11px]">{item.availability}</dd></div>
        <div className="min-w-0 sm:col-span-2"><dt className="text-[11px] text-ink-muted">Core 사유</dt><dd className="break-all font-mono text-[11px]">{item.reason ?? "기록 없음"}</dd></div>
      </dl>
    </details>
    {item.reason && <details className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2"><summary className="tap-target cursor-pointer font-semibold">처리 사유 확인</summary><code className="break-all font-mono">{item.reason}</code></details>}

    {hasReceipt && <ReceiptFacts receipt={item.receipt!} />}
    {isCompleted && !hasReceipt && <p className="rounded-md border border-high/30 bg-high-bg px-3 py-2 text-[12px] leading-5 text-high-ink">
      처리는 완료로 기록됐지만, 해당 요청의 출력 정보를 확인하지 못했습니다. 파일을 제공할 수 없습니다.
    </p>}
    {!isCompleted && item.receipt && <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2">처리 완료 전에는 출력 정보와 파일을 제공하지 않습니다.</p>}

    {hasReceipt && item.availability === "AVAILABLE"
      ? <div className="flex flex-col items-start gap-2 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-2xl text-[12px] leading-5 text-ink-2">파일이 준비되었습니다. 요청한 계정으로만 받을 수 있으며, 내려받을 때 현재 접근 권한과 파일 보관 상태를 다시 확인합니다.</p>
        <a className="btn btn-primary min-h-11 shrink-0" href={fileHref} download>준비된 파일 다운로드</a>
      </div>
      : isCompleted && <p className="rounded-md border border-high/30 bg-high-bg px-3 py-2 text-[12px] leading-5 text-high-ink">
        현재 파일을 제공할 수 없습니다. {AVAILABILITY_LABEL[item.availability]} 상태입니다.
      </p>}

    {hasReceipt && item.availability === "AVAILABLE" && <SpatialDataReceiptPreview
      key={`${siteId}:${item.workAreaId}:${item.jobId}:${item.receipt!.receiptDigest ?? item.receipt!.outputSha256}`}
      siteId={siteId}
      workAreaId={item.workAreaId}
      jobId={item.jobId}
      receipt={item.receipt!}
      fileHref={fileHref}
    />}

    {active && <SpatialDataRequestActions siteId={siteId} workAreaId={item.workAreaId} requestId={item.jobId} canCancel={canCancel} />}
    <Link className="btn min-h-11 w-fit" href={backHref}>요청 목록으로 돌아가기</Link>
  </section>;
}

function RequestRow({
  item,
  siteId,
  workAreaId,
  cursor,
  selected,
  title,
  sourceLine,
  rawSourceKind,
}: {
  item: SpatialDataJobView;
  siteId: string;
  workAreaId: string;
  cursor?: string;
  selected: boolean;
  title: string;
  sourceLine: string;
  rawSourceKind: string | null;
}) {
  const href = pageHref(siteId, workAreaId, { cursor, requestId: item.jobId });
  return <li className={`grid gap-3 px-4 py-4 sm:grid-cols-[minmax(0,1.35fr)_minmax(135px,0.8fr)_minmax(145px,0.8fr)_minmax(145px,0.9fr)] sm:items-center ${selected ? "bg-sunk/70" : "bg-surface"}`}>
    <div className="min-w-0">
      <p className="mb-1 text-[10.5px] text-ink-muted sm:hidden">요청</p>
      <Link href={href} aria-current={selected ? "page" : undefined} className="tap-target inline-block min-h-8 w-full break-words text-left text-[13px] font-semibold text-accent-text hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        {title}
      </Link>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 sm:hidden">
        {stateBadge(item.executionState)}
        {availabilityText(item.availability)}
      </div>
      <p className="mt-1 break-words text-[11.5px] text-ink-2">{sourceLine}</p>
      <details className="mt-1 text-[11.5px]">
        <summary className="tap-target cursor-pointer font-semibold text-ink-muted">요청·원본 처리 상세 보기</summary>
        <div className="mt-1 flex flex-col gap-0.5 break-all border-l-2 border-line pl-2 text-ink-2">
          <p>요청 ID · {item.jobId}</p>
          {rawSourceKind && <p>원본 종류(원문) · {rawSourceKind}</p>}
          <p>원본 assetRef · {item.assetRef}</p>
        </div>
      </details>
    </div>
    <div>
      <p className="mb-1 text-[10.5px] text-ink-muted sm:hidden">생성 시각</p>
      <p className="text-[12px] text-ink-2">{formatKoreanDateTime(item.createdAt, { dateStyle: "medium", timeStyle: "short" })}</p>
    </div>
    <div className="hidden flex-wrap items-center gap-x-2 gap-y-1 sm:flex">
      {stateBadge(item.executionState)}
      {availabilityText(item.availability)}
    </div>
    <div className="min-w-0">
      <p className="mb-1 text-[10.5px] text-ink-muted sm:hidden">처리 사유</p>
      {item.reason
        ? <p className="break-all font-mono text-[11.5px] text-ink-2">{item.reason}</p>
        : <p className="text-[11.5px] text-ink-muted">기록 없음</p>}
    </div>
  </li>;
}

function requestCreationHref(siteId: string, workAreaId?: string, assetRef?: string): string {
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  if (!workAreaId) return `${sitePath}/spatial-assets`;
  const query = new URLSearchParams({ workAreaId });
  // 정확한 자료가 있을 때만 정보 서랍을 연다 — 없으면 기본 A를 열어
  // 다른 자료의 요청 폼을 보여 주는 오해를 만들지 않는다.
  if (assetRef) {
    query.set("assetRef", assetRef);
    query.set("info", "1");
  }
  return `${sitePath}/spatial-assets?${query.toString()}`;
}

function RequestPageHeader({
  siteId,
  siteName,
  workAreaId,
  assetRef,
  canRequestData,
}: {
  siteId: string;
  siteName: string;
  workAreaId?: string;
  /** 만료 미리보기에서 넘어온 정확한 자료 — 이력 페이지만 보고 끝나지 않게 한다. */
  assetRef?: string;
  canRequestData: boolean;
}) {
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const assetHref = requestCreationHref(siteId, workAreaId, assetRef);
  return <header className="flex flex-col gap-3 border-b border-line pb-4 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <p className="text-[12.5px] text-ink-2">{siteName} · 구역 자료</p>
      <h2 className="mt-1 text-[22px] font-bold tracking-tight">구역 자료 준비</h2>
      <p className="mt-1 max-w-3xl text-[13px] leading-5 text-ink-2">작업구역별로 요청한 자료의 준비 상태와 파일을 확인하세요. 자료 준비 완료는 정확도나 분석 사용 가능 여부를 보증하지 않습니다.</p>
    </div>
    <nav aria-label="구역 자료 준비 화면" className="flex flex-wrap gap-2">
      {canRequestData && (
        <Link href={assetHref} className="btn btn-primary min-h-11">
          {assetRef ? "이 자료 새로 준비 요청" : "자료에서 새 준비 요청"}
        </Link>
      )}
      {!canRequestData && <Link href={assetHref} className="btn min-h-11">등록 자료</Link>}
      <Link href={sitePath} className="btn min-h-11">현장으로 돌아가기</Link>
    </nav>
  </header>;
}

export default async function SpatialDataRequestsPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return <OperationsSessionFailure verdict={session.verdict} next={`/sites/${encodeURIComponent(siteId)}/spatial-data-requests`} />;
  }

  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState
      message={error instanceof CoreApiError && error.status === 403 ? "현장 조회 권한이 없습니다." : "현장 정보를 불러오지 못했습니다."}
      tone={error instanceof CoreApiError && error.status === 403 ? "high" : "crit"}
      retryable={!(error instanceof CoreApiError && error.status === 403)}
      retryAfterSeconds={error instanceof CoreApiError ? error.retryAfterSeconds : undefined}
    /></div>;
  }

  const basePath = `/sites/${encodeURIComponent(siteId)}/spatial-data-requests`;
  const header = (workAreaId?: string, assetRef?: string, canRequestData = false) =>
    <RequestPageHeader siteId={siteId} siteName={site.name} workAreaId={workAreaId} assetRef={assetRef} canRequestData={canRequestData} />;
  if (!session.principal.permissions.includes("SPATIAL_DATA_READ")) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">
      {header()}
      <ErrorState message={READ_PERMISSION_MESSAGE} tone="high" />
    </div>;
  }

  const { workAreaId: areaParam, cursor: cursorParam, requestId: requestParam, assetRef: assetParam } = query;
  if (Array.isArray(areaParam)) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}<ErrorState message="작업구역을 하나만 선택하세요." tone="high" action={{ label: "목록으로 돌아가기", href: basePath }} /></div>;
  }
  if (Array.isArray(cursorParam) || typeof cursorParam === "string" && cursorParam.length > 2048) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}<ErrorState message="페이지 커서가 올바르지 않습니다. 목록을 처음부터 다시 열어 주세요." tone="high" action={{ label: "처음부터 보기", href: basePath }} /></div>;
  }
  if (Array.isArray(requestParam) || typeof requestParam === "string" && !REQUEST_ID_PATTERN.test(requestParam)) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}<ErrorState message="요청 ID 형식이 올바르지 않습니다." tone="high" action={{ label: "목록으로 돌아가기", href: basePath }} /></div>;
  }
  if (Array.isArray(assetParam) || typeof assetParam === "string" && !ASSET_REF_PATTERN.test(assetParam)) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}<ErrorState message="자료 참조 형식이 올바르지 않습니다." tone="high" action={{ label: "목록으로 돌아가기", href: basePath }} /></div>;
  }

  const workAreaId = singleQueryValue(areaParam);
  const cursor = singleQueryValue(cursorParam);
  const requestId = singleQueryValue(requestParam);
  const assetRef = singleQueryValue(assetParam);

  let areas: Awaited<ReturnType<typeof listWorkAreas>> | null = null;
  let areasError: unknown = null;
  try {
    areas = await listWorkAreas(siteId, { includeArchived: true });
  } catch (error) {
    areasError = error;
  }
  if (areasError) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}{errorView(areasError, "areas", siteId)}</div>;
  }

  const selectedArea = areas?.workAreas.find((area) => area.workAreaId === workAreaId);
  if (workAreaId && !selectedArea) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}<ErrorState message="작업구역을 확인할 수 없거나 접근 권한이 없습니다." tone="high" action={{ label: "다른 작업구역 선택", href: basePath }} /></div>;
  }

  let page: Awaited<ReturnType<typeof listSpatialDataRequests>> | null = null;
  let pageError: unknown = null;
  if (workAreaId) {
    try {
      page = await listSpatialDataRequests(siteId, workAreaId, { limit: 50, cursor });
    } catch (error) {
      pageError = error;
    }
  }

  let detail: Awaited<ReturnType<typeof getSpatialDataRequest>> | null = null;
  let detailError: unknown = null;
  if (requestId && workAreaId && !pageError) {
    try {
      detail = await getSpatialDataRequest(siteId, workAreaId, requestId);
    } catch (error) {
      detailError = error;
    }
  }

  const canRequestData = session.principal.permissions.includes("SPATIAL_DATA_REQUEST");
  const canCancel = canRequestData;
  // 원본 파일명·종류는 사람용 표시 전용으로, 선택된 구역에서 최대 1회만 읽는다.
  // 실패해도 목록·상세는 그대로 두며, 원본 삭제·부재로 해석하지 않는다.
  let catalogInfo: Record<string, CatalogAssetInfo> | null = null;
  if (workAreaId && !pageError) {
    try {
      const catalog = await listSpatialAssets(siteId, workAreaId, { limit: 50 });
      if (catalog.siteId === siteId && catalog.workAreaId === workAreaId) {
        const map: Record<string, CatalogAssetInfo> = {};
        for (const asset of catalog.assets) {
          map[asset.assetRef] = {
            fileName: asset.declared.fileName,
            kind: asset.kind,
            captureStartedAt: asset.declared.captureStartedAt,
            captureEndedAt: asset.declared.captureEndedAt,
          };
        }
        catalogInfo = map;
      }
    } catch {
      catalogInfo = null;
    }
  }
  const inScopeItems = page?.items.filter((item) => item.siteId === siteId && item.workAreaId === workAreaId) ?? [];
  const invalidStateItems = inScopeItems.filter((item) => !isSpatialDataExecutionState(item.executionState) || !isSpatialDataAvailability(item.availability));
  const scopedItems = inScopeItems.filter((item) => isSpatialDataExecutionState(item.executionState) && isSpatialDataAvailability(item.availability));
  const mismatchedItems = page?.items.filter((item) => item.siteId !== siteId || item.workAreaId !== workAreaId) ?? [];
  const detailMatchesScope = detail !== null && requestId !== undefined && detail.jobId === requestId && detail.siteId === siteId && detail.workAreaId === workAreaId && isSpatialDataExecutionState(detail.executionState) && isSpatialDataAvailability(detail.availability);
  const backHref = workAreaId ? pageHref(siteId, workAreaId, { cursor }) : basePath;
  const rowPresentations = requestRowPresentations(
    scopedItems,
    // 초 단위까지 표시해 분만 같은 요청을 먼저 가른다. 그래도 겹치는 제목에만
    // 원문 요청 ID 전체를 덧붙인다(helper가 판정).
    (iso) => formatKoreanDateTime(iso, { dateStyle: "medium", timeStyle: "medium" }),
    catalogInfo,
    selectedArea?.name ?? workAreaId ?? "",
  );

  const frame = <SiteHeader
    site={site}
    selectedEpochId={null}
    tab="materials"
    canCreateWorkOrder={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
    canEditAoi={session.principal.permissions.includes("SITES_WRITE")}
    scopedWorkAreaId={workAreaId ?? null}
  />;
  return <div className="flex flex-col">
    {frame}
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 sm:p-5">
    {header(workAreaId, assetRef, canRequestData)}

    <section className="rounded-lg border border-line bg-surface px-4 py-3">
      <form action={basePath} method="get" className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-56 flex-col gap-1 text-[12px] font-semibold" htmlFor="spatial-request-work-area">작업구역 선택
          <WorkAreaHistorySelect key={workAreaId ?? ""} value={workAreaId ?? ""}>
            <option value="" disabled>작업구역을 선택하세요</option>
            {areas?.workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}{area.status === "ARCHIVED" ? " · 보관됨" : ""}</option>)}
          </WorkAreaHistorySelect>
        </label>
        <button className="btn btn-primary min-h-11" type="submit">요청 이력 불러오기</button>
      </form>
      <p id="spatial-request-work-area-help" className="mt-2 text-[12px] leading-5 text-ink-muted">구역을 바꾸면 요청 이력을 불러옵니다. 자동으로 열리지 않으면 조회 버튼을 누르세요.</p>
      {areas?.workAreas.length === 0 && <p className="mt-3 text-[12.5px] leading-5 text-ink-2">요청 이력을 조회할 작업구역이 없습니다. 현장 담당자에게 작업구역 등록 여부를 확인하세요.</p>}
      {!workAreaId && <p className="mt-3 text-[12.5px] leading-5 text-ink-2">작업구역을 선택해 해당 구역의 자료 준비 요청을 확인하세요.</p>}
      {workAreaId && selectedArea && <p className="mt-2 text-[12px] text-ink-muted">선택: {selectedArea.name}{selectedArea.status === "ARCHIVED" ? " · 보관됨" : ""} · 페이지당 최대 50건</p>}
    </section>

    {pageError !== null && <div>{errorView(pageError, "list", siteId)}</div>}
    {page && workAreaId && <>
      {mismatchedItems.length > 0 && <ErrorState message="Core 응답에 요청한 Site/WorkArea와 다른 항목이 있어 해당 항목을 숨겼습니다." tone="high" />}
      {invalidStateItems.length > 0 && <ErrorState message="Core 응답에 계약되지 않은 실행 상태 또는 availability가 있어 해당 항목을 숨겼습니다." tone="high" />}
      {requestId && detailError && <div>{errorView(detailError, "detail", siteId)}</div>}
      {detail && !detailMatchesScope && <ErrorState message="Core 응답 요청의 ID 또는 Site/WorkArea 범위가 요청과 일치하지 않아 상세를 표시하지 않았습니다." tone="high" />}
      {detail && detailMatchesScope && <RequestDetail item={detail} siteId={siteId} workAreaName={selectedArea?.name ?? workAreaId} assetInfo={catalogInfo?.[detail.assetRef] ?? null} canCancel={canCancel} backHref={backHref} />}

      <section className="overflow-hidden rounded-xl border border-line bg-surface">
        <header className="flex flex-wrap items-end justify-between gap-2 border-b border-line px-4 py-3">
          <div><h2 className="text-[15px] font-bold">요청 이력</h2><p className="mt-1 text-[11.5px] text-ink-muted">현재 페이지 {formatCountKo(scopedItems.length)}건 · 생성 시각은 Core 기록</p></div>
          <span className="text-[11px] text-ink-muted">최신 상태를 다시 조회하려면 페이지를 새로 고치세요.</span>
        </header>
        {scopedItems.length === 0
          ? <div className="p-4"><EmptyState
            compact
            title={cursor ? "이 페이지에 표시할 요청이 없습니다" : "이 작업구역의 자료 준비 요청이 없습니다"}
            description={cursor
              ? "Core가 반환한 현재 페이지가 비어 있습니다. 처음부터 다시 열어 첫 페이지를 확인하세요."
              : "등록 자료에서 이 자료 받기 요청을 만들면 상태와 출력 근거가 이곳에 표시됩니다."}
            action={canRequestData && !cursor
              ? {
                  label: assetRef ? "이 자료 새로 준비 요청" : "자료에서 새 준비 요청",
                  href: requestCreationHref(siteId, workAreaId, assetRef),
                }
              : undefined}
          /></div>
          : <>
            <div className="hidden border-b border-line bg-sunk/60 px-4 py-2 text-[10.5px] font-semibold text-ink-muted sm:grid sm:grid-cols-[minmax(0,1.35fr)_minmax(135px,0.8fr)_minmax(145px,0.8fr)_minmax(145px,0.9fr)]"><span>요청</span><span>생성 시각</span><span>상태 · 접근 가능 여부</span><span>처리 사유</span></div>
            <ul className="divide-y divide-line">
              {scopedItems.map((item, position) => REQUEST_ID_PATTERN.test(item.jobId)
                ? <RequestRow key={item.jobId} item={item} siteId={siteId} workAreaId={workAreaId} cursor={cursor} selected={requestId === item.jobId} title={rowPresentations[position]!.title} sourceLine={rowPresentations[position]!.sourceLine} rawSourceKind={rowPresentations[position]!.rawSourceKind} />
                : <li key={String(item.jobId)} className="p-4"><ErrorState message="Core 응답에 유효하지 않은 요청 ID가 있어 해당 항목을 숨겼습니다." tone="high" /></li>)}
            </ul>
          </>}
      </section>

      <nav aria-label="요청 이력 페이지" className="flex flex-wrap gap-2">
        {cursor && <Link className="btn min-h-11" href={pageHref(siteId, workAreaId)}>처음부터 보기</Link>}
        {page.nextCursor && <Link className="btn btn-primary min-h-11" href={pageHref(siteId, workAreaId, { cursor: page.nextCursor })}>다음 요청 보기</Link>}
      </nav>
    </>}
    </div>
  </div>;
}
