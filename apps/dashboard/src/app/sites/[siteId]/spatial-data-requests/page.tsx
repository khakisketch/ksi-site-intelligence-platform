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
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatCountKo, formatNumberKo } from "@/lib/number-format";

import { SpatialDataRequestActions } from "./SpatialDataRequestActions";

export const metadata = { title: "구역 데이터 요청 · KSI" };

type SearchValue = string | string[] | undefined;
type SearchParams = { workAreaId?: SearchValue; cursor?: SearchValue; requestId?: SearchValue };

const REQUEST_ID_PATTERN = /^sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ACTIVE_STATES: readonly SpatialDataExecutionState[] = ["QUEUED", "RUNNING"];
const READ_PERMISSION_MESSAGE = "이 현장의 공간 데이터 요청을 볼 권한이 없습니다. 현장 담당자에게 접근 권한을 요청하세요.";

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
  AVAILABLE: "Core에서 접근 가능",
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
      return <ErrorState message="Core에서 공간 데이터 요청을 일시적으로 불러오지 못했습니다." retryable retryAfterSeconds={error.retryAfterSeconds} />;
    }
    return <ErrorState message="요청 정보를 확인할 수 없습니다." tone="high" />;
  }
  return <ErrorState message="공간 데이터 요청 정보를 Core에서 불러오지 못했습니다." retryable />;
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="min-w-0">
    <dt className="text-[11px] text-ink-muted">{label}</dt>
    <dd className={`mt-0.5 break-words text-[12.5px] text-ink-2 ${mono ? "font-mono text-[11px]" : ""}`}>{value}</dd>
  </div>;
}

function formatTuple(values: readonly number[] | undefined): string {
  if (!values || values.some((value) => !Number.isFinite(value))) return "Core 값 형식을 확인할 수 없음";
  return `[${values.map((value) => formatNumberKo(value, 4)).join(", ")}]`;
}

function exactBytes(value: number): string {
  return Number.isSafeInteger(value) && value >= 0 ? formatBytesKo(value) : "정확한 크기 표시 불가";
}

function ReceiptFacts({ receipt }: { receipt: SpatialDataReceipt }) {
  return <section className="border-t border-line pt-4">
    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line pb-3">
      <div>
        <h3 className="text-[15px] font-bold">Core 작업 receipt</h3>
        <p className="mt-1 text-[11.5px] text-ink-muted">COMPLETED 요청의 출력·공간 사실. 이 receipt는 정확도 평가나 현장 적합성 판정이 아닙니다.</p>
      </div>
      {receipt.receiptDigest && <span className="max-w-full break-all font-mono text-[10.5px] text-ink-muted">receipt {receipt.receiptDigest}</span>}
    </div>
    <dl className="mt-4 grid gap-x-5 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
      <Fact label="산출물 종류" value={receipt.artifactKind} mono />
      <Fact label="출력 크기" value={exactBytes(receipt.outputSizeBytes)} />
      <Fact label="출력 SHA-256" value={receipt.outputSha256} mono />
      <Fact label="픽셀 창 (Core 순서)" value={formatTuple(receipt.pixelWindow)} mono />
      <Fact label="출력 픽셀 크기" value={`${formatCountKo(receipt.width)} × ${formatCountKo(receipt.height)} pixels`} />
      <Fact label="실제 bounds (Core 순서)" value={formatTuple(receipt.actualBounds)} mono />
      <Fact label="요청 bounds (Core 순서)" value={formatTuple(receipt.requestedBounds)} mono />
      <Fact label="관측 CRS" value={receipt.observedCrsIdentifier} mono />
      <Fact label="관측 CRS digest" value={receipt.observedCrsDigest} mono />
      <Fact label="준비 시각" value={formatKoreanDateTime(receipt.preparedAt, { dateStyle: "medium", timeStyle: "short" })} />
      <Fact label="정확도 평가" value="수행하지 않음 (accuracyAssessed=false)" />
    </dl>
    <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
      <div><p className="text-[11px] text-ink-muted">Attribution</p><p className="mt-1 break-words text-[12.5px] leading-5 text-ink-2">{receipt.attribution}</p></div>
      <div><p className="text-[11px] text-ink-muted">Modification notice</p><p className="mt-1 break-words text-[12.5px] leading-5 text-ink-2">{receipt.modificationNotice}</p></div>
    </div>
    <div className="mt-3 rounded-md border border-high/30 bg-high-bg px-3 py-2 text-[11.5px] leading-5 text-high-ink">
      <p className="font-semibold">해석 범위</p>
      <p className="mt-0.5">파일 준비와 receipt 기록은 CRS 기준의 현장 정확도, 측량·정산 적합성 또는 분석 적격성을 보증하지 않습니다.</p>
      {receipt.limitations.length > 0 && <ul className="mt-1 list-disc pl-5">{receipt.limitations.map((limitation, index) => <li key={`${index}-${limitation}`} className="break-words">{limitation}</li>)}</ul>}
    </div>
  </section>;
}

function RequestDetail({
  item,
  siteId,
  workAreaName,
  canCancel,
  backHref,
}: {
  item: SpatialDataJobView;
  siteId: string;
  workAreaName: string;
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
        <h2 className="mt-1 text-[16px] font-bold tracking-tight break-keep">{workAreaName} · {formatKoreanDateTime(item.createdAt, { dateStyle: "medium", timeStyle: "short" })}</h2>
        <p className="mt-1 break-all font-mono text-[11px] text-ink-muted">요청 ID · {item.jobId}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">{stateBadge(item.executionState)}{availabilityText(item.availability)}</div>
    </header>
    <dl className="grid gap-3 sm:grid-cols-2">
      <Fact label="Site / WorkArea" value={`${item.siteId} / ${item.workAreaId}`} mono />
      <Fact label="원본 assetRef" value={item.assetRef} mono />
      <Fact label="생성 시각" value={formatKoreanDateTime(item.createdAt, { dateStyle: "medium", timeStyle: "short" })} />
      <Fact label="Core 실행 상태" value={item.executionState} mono />
      <Fact label="Core availability" value={item.availability} mono />
      <Fact label="Core 사유" value={item.reason ?? "기록 없음"} mono />
    </dl>
    {item.reason && <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2"><span className="font-semibold">Core 사유 (원문): </span><code className="break-all font-mono">{item.reason}</code></p>}

    {hasReceipt && <ReceiptFacts receipt={item.receipt!} />}
    {isCompleted && !hasReceipt && <p className="rounded-md border border-high/30 bg-high-bg px-3 py-2 text-[12px] leading-5 text-high-ink">
      Core 상태는 COMPLETED이나 일치하는 receipt가 없어 출력 근거를 표시하지 않습니다.
    </p>}
    {!isCompleted && item.receipt && <p className="rounded-md border border-line bg-sunk px-3 py-2 text-[12px] leading-5 text-ink-2">요청 상태가 COMPLETED가 아니므로 receipt와 파일 결과를 표시하지 않습니다.</p>}

    {hasReceipt && item.availability === "AVAILABLE"
      ? <div className="flex flex-col items-start gap-2 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-2xl text-[12px] leading-5 text-ink-2">현재 Core availability가 AVAILABLE인 완료 출력입니다. 내려받기 시에도 Core가 현재 권한과 바이트를 다시 확인합니다. 바이트는 Core가 요청 주체에게 전달하므로, 현재 세션이 요청 주체와 다르면 Core가 거부합니다.</p>
        <a className="btn btn-primary min-h-11 shrink-0" href={fileHref} download>준비된 파일 다운로드</a>
      </div>
      : isCompleted && <p className="rounded-md border border-high/30 bg-high-bg px-3 py-2 text-[12px] leading-5 text-high-ink">
        현재 availability가 {item.availability}이므로 이 화면에서 파일을 제공하지 않습니다.
      </p>}

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
}: {
  item: SpatialDataJobView;
  siteId: string;
  workAreaId: string;
  cursor?: string;
  selected: boolean;
}) {
  const href = pageHref(siteId, workAreaId, { cursor, requestId: item.jobId });
  return <li className={`grid gap-3 px-4 py-4 sm:grid-cols-[minmax(0,1.35fr)_minmax(135px,0.8fr)_minmax(145px,0.8fr)_minmax(145px,0.9fr)] sm:items-center ${selected ? "bg-sunk/70" : "bg-surface"}`}>
    <div className="min-w-0">
      <p className="mb-1 text-[10.5px] text-ink-muted sm:hidden">요청 · 원본 자산</p>
      <Link href={href} aria-current={selected ? "page" : undefined} className="tap-target inline-flex min-h-8 max-w-full items-center text-[13px] font-semibold text-accent-text hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        이 요청 열기
      </Link>
      <p className="mt-1 break-all font-mono text-[10.5px] text-ink-muted">{item.jobId}</p>
    </div>
    <div>
      <p className="mb-1 text-[10.5px] text-ink-muted sm:hidden">생성 시각</p>
      <p className="text-[12px] text-ink-2">{formatKoreanDateTime(item.createdAt, { dateStyle: "medium", timeStyle: "short" })}</p>
    </div>
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <p className="mb-1 w-full text-[10.5px] text-ink-muted sm:hidden">실행 상태 · availability</p>
      {stateBadge(item.executionState)}
      {availabilityText(item.availability)}
    </div>
    <div className="min-w-0">
      <p className="mb-1 text-[10.5px] text-ink-muted sm:hidden">Core 사유</p>
      {item.reason
        ? <p className="break-all font-mono text-[11.5px] text-ink-2">{item.reason}</p>
        : <p className="text-[11.5px] text-ink-muted">기록 없음</p>}
    </div>
  </li>;
}

function RequestPageHeader({ siteId, siteName, workAreaId }: { siteId: string; siteName: string; workAreaId?: string }) {
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const assetHref = workAreaId
    ? `/sites/${encodeURIComponent(siteId)}/spatial-assets?workAreaId=${encodeURIComponent(workAreaId)}`
    : `/sites/${encodeURIComponent(siteId)}/spatial-assets`;
  return <header className="flex flex-col gap-3 border-b border-line pb-4 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <p className="text-[12.5px] text-ink-2">{siteName} · 공간 데이터</p>
      <h2 className="mt-1 text-[22px] font-bold tracking-tight">구역 데이터 요청</h2>
      <p className="mt-1 max-w-3xl text-[13px] leading-5 text-ink-2">WorkArea별 Core 요청 상태와 준비된 출력 receipt를 확인합니다. 이 화면은 권한이 허용된 기록만 표시하며, 처리 결과를 정확도나 분석 적합성으로 해석하지 않습니다.</p>
    </div>
    <nav aria-label="공간 데이터 화면" className="flex flex-wrap gap-2">
      <Link href={assetHref} className="btn min-h-11">공간 자산</Link>
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
      message={error instanceof CoreApiError && error.status === 403 ? "현장 조회 권한이 없습니다." : "현장 정보를 Core에서 불러오지 못했습니다."}
      tone={error instanceof CoreApiError && error.status === 403 ? "high" : "crit"}
      retryable={!(error instanceof CoreApiError && error.status === 403)}
      retryAfterSeconds={error instanceof CoreApiError ? error.retryAfterSeconds : undefined}
    /></div>;
  }

  const basePath = `/sites/${encodeURIComponent(siteId)}/spatial-data-requests`;
  const header = (workAreaId?: string) => <RequestPageHeader siteId={siteId} siteName={site.name} workAreaId={workAreaId} />;
  if (!session.principal.permissions.includes("SPATIAL_DATA_READ")) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">
      {header()}
      <ErrorState message={READ_PERMISSION_MESSAGE} tone="high" />
    </div>;
  }

  const { workAreaId: areaParam, cursor: cursorParam, requestId: requestParam } = query;
  if (Array.isArray(areaParam)) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}<ErrorState message="작업구역을 하나만 선택하세요." tone="high" action={{ label: "목록으로 돌아가기", href: basePath }} /></div>;
  }
  if (Array.isArray(cursorParam) || typeof cursorParam === "string" && cursorParam.length > 2048) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}<ErrorState message="페이지 커서가 올바르지 않습니다. 목록을 처음부터 다시 열어 주세요." tone="high" action={{ label: "처음부터 보기", href: basePath }} /></div>;
  }
  if (Array.isArray(requestParam) || typeof requestParam === "string" && !REQUEST_ID_PATTERN.test(requestParam)) {
    return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">{header()}<ErrorState message="요청 ID 형식이 올바르지 않습니다." tone="high" action={{ label: "목록으로 돌아가기", href: basePath }} /></div>;
  }

  const workAreaId = singleQueryValue(areaParam);
  const cursor = singleQueryValue(cursorParam);
  const requestId = singleQueryValue(requestParam);

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

  const canCancel = session.principal.permissions.includes("SPATIAL_DATA_REQUEST");
  const inScopeItems = page?.items.filter((item) => item.siteId === siteId && item.workAreaId === workAreaId) ?? [];
  const invalidStateItems = inScopeItems.filter((item) => !isSpatialDataExecutionState(item.executionState) || !isSpatialDataAvailability(item.availability));
  const scopedItems = inScopeItems.filter((item) => isSpatialDataExecutionState(item.executionState) && isSpatialDataAvailability(item.availability));
  const mismatchedItems = page?.items.filter((item) => item.siteId !== siteId || item.workAreaId !== workAreaId) ?? [];
  const detailMatchesScope = detail !== null && requestId !== undefined && detail.jobId === requestId && detail.siteId === siteId && detail.workAreaId === workAreaId && isSpatialDataExecutionState(detail.executionState) && isSpatialDataAvailability(detail.availability);
  const backHref = workAreaId ? pageHref(siteId, workAreaId, { cursor }) : basePath;

  return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">
    {header(workAreaId)}

    <section className="rounded-lg border border-line bg-surface px-4 py-3">
      <form action={basePath} method="get" className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-56 flex-col gap-1 text-[12px] font-semibold" htmlFor="spatial-request-work-area">작업구역 선택
          <select id="spatial-request-work-area" name="workAreaId" className="input" defaultValue={workAreaId ?? ""} required>
            <option value="" disabled>작업구역을 선택하세요</option>
            {areas?.workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}{area.status === "ARCHIVED" ? " · 보관됨" : ""}</option>)}
          </select>
        </label>
        <button className="btn btn-primary min-h-11" type="submit">요청 이력 불러오기</button>
      </form>
      {areas?.workAreas.length === 0 && <p className="mt-3 text-[12.5px] leading-5 text-ink-2">요청 이력을 조회할 작업구역이 없습니다. 현장 담당자에게 작업구역 등록 여부를 확인하세요.</p>}
      {!workAreaId && <p className="mt-3 text-[12.5px] leading-5 text-ink-2">현장의 작업구역 하나를 선택하면 그 범위에 귀속된 공간 데이터 요청을 Core에서 조회합니다.</p>}
      {workAreaId && selectedArea && <p className="mt-2 text-[12px] text-ink-muted">선택: {selectedArea.name}{selectedArea.status === "ARCHIVED" ? " · 보관됨" : ""} · 페이지당 최대 50건</p>}
    </section>

    {pageError !== null && <div>{errorView(pageError, "list", siteId)}</div>}
    {page && workAreaId && <>
      {mismatchedItems.length > 0 && <ErrorState message="Core 응답에 요청한 Site/WorkArea와 다른 항목이 있어 해당 항목을 숨겼습니다." tone="high" />}
      {invalidStateItems.length > 0 && <ErrorState message="Core 응답에 계약되지 않은 실행 상태 또는 availability가 있어 해당 항목을 숨겼습니다." tone="high" />}
      {requestId && detailError && <div>{errorView(detailError, "detail", siteId)}</div>}
      {detail && !detailMatchesScope && <ErrorState message="Core 응답 요청의 ID 또는 Site/WorkArea 범위가 요청과 일치하지 않아 상세를 표시하지 않았습니다." tone="high" />}
      {detail && detailMatchesScope && <RequestDetail item={detail} siteId={siteId} workAreaName={selectedArea?.name ?? workAreaId} canCancel={canCancel} backHref={backHref} />}

      <section className="overflow-hidden rounded-xl border border-line bg-surface">
        <header className="flex flex-wrap items-end justify-between gap-2 border-b border-line px-4 py-3">
          <div><h2 className="text-[15px] font-bold">요청 이력</h2><p className="mt-1 text-[11.5px] text-ink-muted">현재 페이지 {formatCountKo(scopedItems.length)}건 · 생성 시각은 Core 기록</p></div>
          <span className="text-[11px] text-ink-muted">최신 상태를 다시 조회하려면 페이지를 새로 고치세요.</span>
        </header>
        {scopedItems.length === 0
          ? <div className="p-4"><EmptyState compact title={cursor ? "이 페이지에 표시할 요청이 없습니다" : "이 작업구역의 공간 데이터 요청이 없습니다"} description={cursor ? "Core가 반환한 현재 페이지가 비어 있습니다. 처음부터 다시 열어 첫 페이지를 확인하세요." : "공간 자산 화면에서 요청을 시작하면 상태와 출력 근거가 이곳에 표시됩니다."} /></div>
          : <>
            <div className="hidden border-b border-line bg-sunk/60 px-4 py-2 text-[10.5px] font-semibold text-ink-muted sm:grid sm:grid-cols-[minmax(0,1.35fr)_minmax(135px,0.8fr)_minmax(145px,0.8fr)_minmax(145px,0.9fr)]"><span>요청 · 원본 자산</span><span>생성 시각</span><span>상태 · availability</span><span>Core 사유</span></div>
            <ul className="divide-y divide-line">
              {scopedItems.map((item) => REQUEST_ID_PATTERN.test(item.jobId)
                ? <RequestRow key={item.jobId} item={item} siteId={siteId} workAreaId={workAreaId} cursor={cursor} selected={requestId === item.jobId} />
                : <li key={String(item.jobId)} className="p-4"><ErrorState message="Core 응답에 유효하지 않은 요청 ID가 있어 해당 항목을 숨겼습니다." tone="high" /></li>)}
            </ul>
          </>}
      </section>

      <nav aria-label="요청 이력 페이지" className="flex flex-wrap gap-2">
        {cursor && <Link className="btn min-h-11" href={pageHref(siteId, workAreaId)}>처음부터 보기</Link>}
        {page.nextCursor && <Link className="btn btn-primary min-h-11" href={pageHref(siteId, workAreaId, { cursor: page.nextCursor })}>다음 요청 보기</Link>}
      </nav>
    </>}
  </div>;
}
