import { notFound } from "next/navigation";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getObservationWorkOrder } from "@/lib/core-api/observation-work-orders";
import { getSiteExternalRelativeVolumeReport } from "@/lib/core-api/external-result-workflow";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { isExternalRelativeVolumeReportReference } from "@/lib/external-relative-volume-references";

import { ExternalObservationCreateForm } from "./ExternalObservationCreateForm";

async function loadNewObservation(siteId: string) {
  try {
    const [site, areas, canCreate] = await Promise.all([
      getSite(siteId),
      listWorkAreas(siteId),
      hasAllPermissions("WORK_ORDERS_WRITE"),
    ]);
    return { kind: "ready" as const, site, areas, canCreate };
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) return { kind: "not-found" as const };
    return {
      kind: "error" as const,
      message: error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "새 관측에 필요한 현장 정보를 불러오지 못했습니다.",
    };
  }
}

type RepeatObservationTemplate = {
  initialWorkAreaIds: string[];
  temporalPolicy: Awaited<ReturnType<typeof getObservationWorkOrder>>["temporalPolicy"] | null;
  suggestedName: string | null;
  notice: string | null;
};

function suggestedRepeatName(name: string, cycleNumber: number): string | null {
  const sourceName = name.trim();
  if (!sourceName) return null;
  const nextCycleNumber = cycleNumber + 1;
  const nextCycle = Number.isSafeInteger(cycleNumber) && cycleNumber >= 0 && Number.isSafeInteger(nextCycleNumber)
    ? ` · ${nextCycleNumber}회차`
    : "";
  const baseLimit = 200 - nextCycle.length;
  const boundedName = sourceName.length > baseLimit
    ? `${sourceName.slice(0, Math.max(0, baseLimit - 1)).trimEnd()}…`
    : sourceName;
  return `${boundedName}${nextCycle}`;
}

async function resolveRepeatObservationTemplate({
  siteId,
  activeAreaIds,
  repeatReportRef,
  repeatWorkOrderId,
}: {
  siteId: string;
  activeAreaIds: ReadonlySet<string>;
  repeatReportRef?: string;
  repeatWorkOrderId?: string;
}): Promise<RepeatObservationTemplate> {
  if (repeatReportRef !== undefined) {
    if (!isExternalRelativeVolumeReportReference(repeatReportRef)) {
      return { initialWorkAreaIds: [], temporalPolicy: null, suggestedName: null, notice: "선택한 이전 비교 결과 주소를 확인하지 못했습니다. 새 관측을 만들려면 작업구역을 직접 선택하세요." };
    }
    const projection = await getSiteExternalRelativeVolumeReport(siteId, repeatReportRef).catch(() => null);
    const result = projection?.state === "AVAILABLE" ? projection.result ?? null : null;
    if (!result || result.reportRef !== repeatReportRef) {
      return { initialWorkAreaIds: [], temporalPolicy: null, suggestedName: null, notice: "선택한 이전 비교 결과를 확인하지 못했습니다. 새 관측을 만들려면 작업구역을 직접 선택하세요." };
    }
    const source = await getObservationWorkOrder(result.currentWorkOrderId).catch(() => null);
    if (!source || source.workOrderId !== result.currentWorkOrderId || source.siteId !== siteId || !source.workAreaIds.includes(result.workAreaId)) {
      return { initialWorkAreaIds: [], temporalPolicy: null, suggestedName: null, notice: "선택한 이전 비교의 작업 범위를 확인하지 못했습니다. 새 관측을 만들려면 작업구역을 직접 선택하세요." };
    }
    if (!activeAreaIds.has(result.workAreaId)) {
      return { initialWorkAreaIds: [], temporalPolicy: null, suggestedName: null, notice: "이전 비교의 작업구역이 현재 활성 상태가 아닙니다. 새 관측에 사용할 작업구역을 직접 선택하세요." };
    }
    return {
      initialWorkAreaIds: [result.workAreaId],
      temporalPolicy: source.temporalPolicy ?? null,
      suggestedName: suggestedRepeatName(source.name, source.cycleNumber),
      notice: "이전 비교에 사용한 활성 작업구역과 촬영 간격 기준을 미리 골랐습니다. 새 관측을 만들기 전에 범위를 확인하세요.",
    };
  }

  if (repeatWorkOrderId !== undefined) {
    const repeat = await getObservationWorkOrder(repeatWorkOrderId).catch(() => null);
    const canReuse = repeat !== null
      && repeat.workOrderId === repeatWorkOrderId
      && repeat.siteId === siteId
      && repeat.executionMode === "EXTERNAL_RECONSTRUCTION";
    if (!canReuse || !repeat) {
      return {
        initialWorkAreaIds: [],
        temporalPolicy: null,
        suggestedName: null,
        notice: "이전 관측 작업의 범위를 확인하지 못했습니다. 새 관측을 만들려면 작업구역을 직접 선택하세요.",
      };
    }
    const initialWorkAreaIds = repeat.workAreaIds.filter((workAreaId) => activeAreaIds.has(workAreaId));
    if (initialWorkAreaIds.length === 0) {
      return {
        initialWorkAreaIds: [],
        temporalPolicy: null,
        suggestedName: null,
        notice: "이전 관측의 작업구역이 현재 활성 상태가 아닙니다. 새 관측에 사용할 작업구역을 직접 선택하세요.",
      };
    }
    const allAreasActive = initialWorkAreaIds.length === repeat.workAreaIds.length;
    return {
      initialWorkAreaIds,
      temporalPolicy: repeat.temporalPolicy ?? null,
      suggestedName: null,
      notice: allAreasActive
        ? "이전 관측의 활성 작업구역과 촬영 간격 기준을 미리 골랐습니다. 새 관측을 만들기 전에 범위를 확인하세요."
        : "이전 관측에서 현재 활성인 작업구역과 촬영 간격 기준을 미리 골랐습니다. 비활성 작업구역은 제외했으니 범위를 확인하세요.",
    };
  }

  return {
    initialWorkAreaIds: [],
    temporalPolicy: null,
    suggestedName: null,
    notice: null,
  };
}

export default async function NewObservationPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ repeatWorkOrderId?: string; repeatReportRef?: string }>;
}) {
  const { siteId } = await params;
  const { repeatWorkOrderId, repeatReportRef } = await searchParams;
  const result = await loadNewObservation(siteId);
  if (result.kind === "not-found") notFound();
  if (result.kind === "error") {
    return <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5"><ErrorState message={result.message} retryable /></div>;
  }
  if (!result.canCreate) {
    return <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-5"><EmptyState title="새 관측을 등록할 권한이 없습니다" description="작업 등록 권한이 있는 계정으로 다시 시도하세요." action={{ label: "현장으로 돌아가기", href: `/sites/${encodeURIComponent(siteId)}` }} /></div>;
  }
  const activeAreaIds = new Set(result.areas.workAreas.map((area) => area.workAreaId));
  const repeatTemplate = await resolveRepeatObservationTemplate({
    siteId: result.site.siteId,
    activeAreaIds,
    repeatReportRef,
    repeatWorkOrderId,
  });
  return <ExternalObservationCreateForm
    key={`${repeatReportRef ?? ""}:${repeatWorkOrderId ?? ""}`}
    siteId={result.site.siteId}
    siteName={result.site.name}
    workAreas={result.areas.workAreas.map((area) => ({ workAreaId: area.workAreaId, name: area.name }))}
    initialWorkAreaIds={repeatTemplate.initialWorkAreaIds}
    temporalPolicy={repeatTemplate.temporalPolicy}
    suggestedName={repeatTemplate.suggestedName}
    templateNotice={repeatTemplate.notice}
  />;
}
