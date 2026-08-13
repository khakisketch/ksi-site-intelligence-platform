"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { DiffHeatmapOverlay } from "@/components/map/DiffHeatmapOverlay";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { PROCESSING_JOB_STATUS_LABEL } from "@/app/missions/mission-labels";
import { humanizeVerticalDatum, readableApiError } from "@/lib/core-api/labels";
import {
  describeVolumeUncertainty,
  formatNetVolumeM3,
  formatVolumeM3,
} from "@/lib/core-api/phase34-labels";
import { isTerminalComparisonStatus, toZonesPayload } from "@/lib/comparison-submit";
import { conformanceReadySurfaces, designComparableJobs } from "@/lib/design-conformance";
import { parseJsonSafe } from "@/lib/http";
import { usePolling } from "@/hooks/usePolling";
import type {
  AoiVertex,
  DesignConformanceEntry,
  DesignConformanceRequestListResponse,
  DesignConformanceRequestMutationResponse,
  DesignConformanceRequestView,
  DesignSurface,
  ProgressBaselineResponse,
  SiteProcessingJobSummary,
  WorkArea,
} from "@/lib/core-api/types";

/**
 * 설계 대비 잔량 — "설계까지 얼마나 남았나"를 요청하고 결과를 읽는다(M4-A).
 *
 * `ComparisonSubmitPanel` 의 형제다: 계산은 워커가 하고 이 화면은 **무엇을 무엇과,
 * 어느 구역에서** 견줄지만 정한다. 세 가지가 저쪽과 다르다.
 *
 * 1. **검증이 끝난 설계면만 고를 수 있다.** `VERIFIED` 가 아닌 자산은 목록에
 *    올리지 않는다 — 아무도 열어보지 않은 파일로 잔량 숫자가 나오면 그 숫자가
 *    무엇을 근거로 하는지 아무도 말할 수 없다(서버도 `DESIGN_SURFACE_NOT_VERIFIED`
 *    로 막지만, 고르게 해 놓고 누른 뒤 거부하는 것은 막다른 길이다).
 * 2. **구역 확정은 선택이 아니라 필수다.** 두 시점 비교는 구역 없이도 변화만
 *    잴 수 있지만, "설계까지 얼마나 남았나"는 범위 없이는 질문 자체가 성립하지
 *    않는다(서버 `ZONES_REQUIRED`).
 * 3. **결과 표와 지도가 같은 격자에서 나온다.** 히트맵은 워커가 체적 집계에
 *    실제로 쓴 차분 래스터를 그대로 받아 그린다 — 브라우저가 다시 차분하지
 *    않는다(그러면 지도와 표가 갈릴 수 있는 두 번째 진실이 생긴다).
 */

function formatJob(job: SiteProcessingJobSummary): string {
  const when = new Date(job.issuedAt);
  const stamp = Number.isNaN(when.getTime())
    ? job.issuedAt
    : when.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
  return `${stamp} · ${job.jobId}`;
}

/** 구역 한 칸 — 부호 규약은 서버 계약이 정한 것을 그대로 말로 옮긴다. */
function ZoneRow({ zone }: { zone: DesignConformanceEntry["report"]["zones"][number] }) {
  const uncertainty = describeVolumeUncertainty(zone.uncertaintyM3, zone.uncertaintyNote);
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[13px] font-bold break-keep">{zone.zoneId}</span>
        <span className="text-[12.5px] text-ink-2">
          면적 {zone.areaM2.toLocaleString("ko-KR", { maximumFractionDigits: 0 })} m²
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <p className="text-[11.5px] break-keep text-ink-2">더 깎아야 함</p>
          <p className="text-[15px] font-bold tabular-nums">{formatVolumeM3(zone.cutM3)}</p>
        </div>
        <div>
          <p className="text-[11.5px] break-keep text-ink-2">더 쌓아야 함</p>
          <p className="text-[15px] font-bold tabular-nums">{formatVolumeM3(zone.fillM3)}</p>
        </div>
        <div>
          <p className="text-[11.5px] break-keep text-ink-2">순 잔량(쌓기−깎기)</p>
          <p className="text-[15px] font-bold tabular-nums">{formatNetVolumeM3(zone.netM3)}</p>
        </div>
      </div>
      <p className="text-[12px] break-keep text-ink-muted">
        높이차가 {zone.thresholdM} m 미만인 곳은 재구성 잡음으로 보고 세지 않았습니다.
      </p>
      <p
        className={
          uncertainty.missing
            ? "rounded-md border border-line-strong bg-sunk px-2.5 py-2 text-[12.5px] break-keep text-ink-2"
            : "text-[12.5px] break-keep text-ink-2"
        }
      >
        {uncertainty.text}
      </p>
    </li>
  );
}

function SetBaselineButton({
  missionId,
  canIssue,
  designSurfaceId,
  designConformanceId,
}: {
  missionId: string;
  canIssue: boolean;
  designSurfaceId: string;
  designConformanceId: string;
}) {
  const [state, setState] = useState<"idle" | "saving" | "done" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  if (!canIssue) return null;

  async function handleClick() {
    setState("saving");
    setMessage(null);
    try {
      const response = await fetch(
        `/api/missions/${encodeURIComponent(missionId)}/design-conformance/${encodeURIComponent(designConformanceId)}/progress-baseline`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ designSurfaceId }),
        },
      );
      const body = await parseJsonSafe<ProgressBaselineResponse>(response);
      if (!response.ok) {
        setState("error");
        setMessage(readableApiError(body, "원지형 기준 지정에 실패했습니다"));
        return;
      }
      setState("done");
    } catch {
      setState("error");
      setMessage("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        className="btn w-fit"
        disabled={state === "saving" || state === "done"}
        onClick={() => void handleClick()}
      >
        {state === "saving"
          ? "지정하는 중…"
          : state === "done"
            ? "원지형 기준으로 지정됨"
            : "이 리포트를 원지형 기준으로 지정"}
      </button>
      {message && (
        <span className="text-[12px] break-keep text-crit-ink" role="alert">
          {message}
        </span>
      )}
      {state === "idle" && (
        <span className="text-[12px] break-keep text-ink-muted">
          시공 전 지형으로 낸 리포트일 때만 지정하세요 — 계획 물량의 근거가 됩니다.
        </span>
      )}
    </div>
  );
}

function ConformanceResult({
  missionId,
  siteId,
  canIssue,
  entry,
  totalNetM3,
}: {
  missionId: string;
  siteId: string;
  canIssue: boolean;
  entry: DesignConformanceEntry;
  totalNetM3: number | null;
}) {
  const { report } = entry;
  return (
    <div className="flex flex-col gap-3 border-t border-line pt-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-[13px] font-bold break-keep">구역별 남은 물량</h4>
        {totalNetM3 !== null && (
          <span className="text-[13px] tabular-nums">
            전체 순 잔량 {formatNetVolumeM3(totalNetM3)}
          </span>
        )}
      </div>

      <p className="text-[12px] break-keep text-ink-2">
        {new Date(report.computedAt).toLocaleString("ko-KR")} 계산 · 좌표계 {report.crs} ·
        높이 기준 {humanizeVerticalDatum(report.verticalReference.datum)}
      </p>

      {/* 수직 기준을 숨기지 않는다 — 어느 기준의 높이차인가가 이 숫자의 의미를
          통째로 바꾼다(국내에서 두 기준 차이가 20~30 m 다).
          정산 근거로 쓸 수 없다는 것은 이미 정해진 사실이다(ADR-KSI-016 D6) —
          설계 대비 "남은 물량"은 계약적 오해를 부르기 가장 쉬운 숫자라, 그 한계를
          숫자 바로 옆에서 말한다. */}
      <p className="rounded-md border border-line bg-sunk px-2.5 py-2 text-[12px] break-keep text-ink-2">
        설계 기준면과 현재 지형이 <strong className="font-bold">같은 계열의 높이 기준</strong>
        일 때만 계산합니다 — 근거: {report.verticalReference.basis}. 이 값은 촬영·재구성
        결과에서 나온 <strong className="font-bold">현황 추정치</strong>이며, 검사점 검증이
        없어 정산·기성 근거로 쓸 수 없습니다.
      </p>

      <ul className="flex flex-col gap-2">
        {report.zones.map((zone) => (
          <ZoneRow key={zone.zoneId} zone={zone} />
        ))}
      </ul>

      <dl className="grid grid-cols-1 gap-2 border-t border-line pt-3 text-[12px] sm:grid-cols-3">
        <div>
          <dt className="break-keep text-ink-muted">집계에서 뺀 높이차</dt>
          <dd className="num">{report.policy.volumeThresholdM} m 미만</dd>
        </div>
        <div>
          <dt className="break-keep text-ink-muted">기준 묶음</dt>
          <dd className="num break-token">{report.policy.policyVersion}</dd>
        </div>
        <div>
          <dt className="break-keep text-ink-muted">기준으로 삼은 설계면</dt>
          <dd className="num break-token">{report.designSurfaceRef.designSurfaceId}</dd>
        </div>
      </dl>

      {/* 지도와 표가 **같은 배열**에서 나온다 — 히트맵은 이 리포트가 가리키는
          차분 래스터를 그대로 받아 그리고, 문턱값도 리포트가 실어 온 값을 쓴다. */}
      <DiffHeatmapOverlay
        missionId={missionId}
        designConformanceId={report.designConformanceId}
        thresholdM={report.diffRaster.thresholdM}
      />

      {/* 계획 대비 진척(M4-C)의 입구 둘 — "이게 계획이다" 지정과 "지금까지 얼마나
          됐나" 조회는 다른 화면·다른 시점의 일이라 나란히 둔다. */}
      <div className="flex flex-col gap-2 border-t border-line pt-3">
        <SetBaselineButton
          missionId={missionId}
          canIssue={canIssue}
          designSurfaceId={report.designSurfaceRef.designSurfaceId}
          designConformanceId={report.designConformanceId}
        />
        <Link
          href={`/sites/${encodeURIComponent(siteId)}/progress?designSurfaceId=${encodeURIComponent(report.designSurfaceRef.designSurfaceId)}`}
          className="text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
        >
          이 설계면의 계획 대비 진척 보기 →
        </Link>
      </div>
    </div>
  );
}

export function DesignConformancePanel({
  missionId,
  siteId,
  canIssue,
  surfaces,
  siteJobs,
  siteAoi,
  workAreas,
  initialRequest,
  initialReport,
  initialTotalNetM3,
}: {
  missionId: string;
  siteId: string;
  canIssue: boolean;
  /** 그 현장의 설계면 전부 — 고를 수 있는 것은 검증이 끝난 것뿐이다. */
  surfaces: DesignSurface[];
  siteJobs: SiteProcessingJobSummary[];
  /** 현장 경계 — **초기값으로만** 쓴다(자동 확정하지 않는다). */
  siteAoi: AoiVertex[] | null;
  /** 그 현장에 등록된 작업구역(ACTIVE) — 고르면 다음 시점과 자동으로 이어진다(M4-C). */
  workAreas: WorkArea[];
  /** 새로고침 복원용 — 그 임무의 최신 설계 대비 요청(없으면 null). */
  initialRequest: DesignConformanceRequestView | null;
  /** 이미 계산된 최신 리포트(없으면 null). */
  initialReport: DesignConformanceEntry | null;
  initialTotalNetM3: number | null;
}) {
  const router = useRouter();
  const readySurfaces = useMemo(() => conformanceReadySurfaces(surfaces), [surfaces]);
  const jobs = useMemo(() => designComparableJobs(siteJobs, missionId), [siteJobs, missionId]);

  const [designSurfaceId, setDesignSurfaceId] = useState("");
  const [currentJobId, setCurrentJobId] = useState("");
  // 작업구역이 하나라도 있으면 그쪽을 기본으로 — 있는데 안 쓰면 진척이 다시 끊긴다.
  const [zoneMode, setZoneMode] = useState<"work-areas" | "draw">(
    workAreas.length > 0 ? "work-areas" : "draw",
  );
  const [selectedWorkAreaIds, setSelectedWorkAreaIds] = useState<string[]>([]);
  const [vertices, setVertices] = useState<AoiVertex[]>(siteAoi ?? []);
  const [zonesConfirmed, setZonesConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [request, setRequest] = useState<DesignConformanceRequestView | null>(initialRequest);

  const pendingRequestId =
    request !== null && !isTerminalComparisonStatus(request.status) ? request.requestId : null;

  // Core 에 요청 1건 조회 표면이 없다 — 임무 목록을 읽고 id 로 찾는다.
  usePolling(
    pendingRequestId,
    async (id) => {
      const response = await fetch(
        `/api/missions/${encodeURIComponent(missionId)}/design-conformance-requests`,
      );
      if (!response.ok) return null;
      const body = await parseJsonSafe<DesignConformanceRequestListResponse>(response);
      return body.requests?.find((r) => r.requestId === id) ?? null;
    },
    (req) => isTerminalComparisonStatus(req.status),
    (req) => {
      setRequest(req);
      // 계산이 끝나면 서버 컴포넌트를 다시 태워 리포트를 받아온다 — 사용자에게
      // "새로고침하세요"라고 시키지 않는다. 폴링은 이 tick 에서 멈추므로 이
      // 호출은 한 번만 일어난다.
      if (req.status === "SUCCEEDED") router.refresh();
    },
  );

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      let requestBody: Record<string, unknown>;
      if (zoneMode === "work-areas") {
        if (selectedWorkAreaIds.length === 0) {
          setError("작업구역을 하나 이상 고르세요 — 범위 없이는 남은 물량을 낼 수 없습니다.");
          return;
        }
        requestBody = { designSurfaceId, currentJobId, workAreaIds: selectedWorkAreaIds };
      } else {
        const zonePayload = toZonesPayload(vertices);
        if (zonePayload === null) {
          setError("구역을 먼저 확정하세요 — 범위 없이는 남은 물량을 낼 수 없습니다.");
          return;
        }
        requestBody = {
          designSurfaceId,
          currentJobId,
          zones: zonePayload.zones,
          zoneCrs: zonePayload.zoneCrs,
        };
      }
      const response = await fetch(
        `/api/missions/${encodeURIComponent(missionId)}/design-conformance-requests`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestBody),
        },
      );
      const responseBody = await parseJsonSafe<DesignConformanceRequestMutationResponse>(response);
      if (!response.ok || !responseBody.request) {
        setError(readableApiError(responseBody, "설계 대비 잔량 요청에 실패했습니다"));
        return;
      }
      // 같은 조합의 재요청은 기존 요청을 그대로 돌려준다(ALREADY_REQUESTED) —
      // 오류가 아니라 재사용이므로 그 요청의 상태를 이어서 보여준다.
      setRequest(responseBody.request);
    } catch {
      setError("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    } finally {
      setSubmitting(false);
    }
  }

  const inProgress = request !== null && !isTerminalComparisonStatus(request.status);
  const zoneReady =
    zoneMode === "work-areas"
      ? selectedWorkAreaIds.length > 0
      : zonesConfirmed && vertices.length >= 3;
  const canSubmit =
    canIssue && !submitting && !inProgress && designSurfaceId !== "" && currentJobId !== "" && zoneReady;

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
          설계 대비 잔량
        </h3>
        <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
          검증된 설계면 {readySurfaces.length}건
        </span>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md bg-crit-bg px-3 py-2 text-[12.5px] font-semibold break-keep text-crit-ink"
        >
          {error}
        </p>
      )}

      {!canIssue ? (
        <p className="text-[12.5px] break-keep text-ink-muted">
          잔량 계산을 요청하려면 임무 발급 권한(MISSIONS_ISSUE)이 필요합니다.
        </p>
      ) : readySurfaces.length === 0 ? (
        <p className="text-[12.5px] break-keep text-ink-muted">
          이 현장에는 검증이 끝난 설계 기준면이 없습니다 — 계획고 파일을 먼저 올리고
          검증을 통과해야 잔량을 낼 수 있습니다.{" "}
          <Link
            href={`/sites/${encodeURIComponent(siteId)}/design`}
            className="font-semibold text-accent-text hover:underline"
          >
            설계 기준면 올리기
          </Link>
        </p>
      ) : jobs.length === 0 ? (
        <p className="text-[12.5px] break-keep text-ink-muted">
          이 임무에서 만든 높이 자료(DSM)가 아직 없습니다 — 사진 업로드와 재구성을 먼저
          끝내세요. 설계 대비 잔량은 항상 그 지형을 만든 임무 화면에서 시작합니다.
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:gap-4">
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-[11.5px] break-keep text-ink-muted">
                설계 기준면 — 검증이 끝난 것만
              </span>
              <select
                className="input"
                value={designSurfaceId}
                disabled={inProgress}
                onChange={(event) => {
                  setDesignSurfaceId(event.target.value);
                  setError(null);
                }}
              >
                <option value="">고르세요</option>
                {readySurfaces.map((surface) => (
                  <option key={surface.designSurfaceId} value={surface.designSurfaceId}>
                    {surface.name} · {surface.revision}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-[11.5px] break-keep text-ink-muted">
                현재 지형 — 이 임무의 재구성 결과
              </span>
              <select
                className="input"
                value={currentJobId}
                disabled={inProgress}
                onChange={(event) => {
                  setCurrentJobId(event.target.value);
                  setError(null);
                }}
              >
                <option value="">고르세요</option>
                {jobs.map((job) => (
                  <option key={job.jobId} value={job.jobId}>
                    {formatJob(job)}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {/* ── 구역 선택: 작업구역(권장) vs 즉석 그리기 ───────────────── */}
          <div className="flex flex-col gap-2 border-t border-line pt-3">
            {workAreas.length > 0 && (
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="구역 선택 방식">
                <button
                  type="button"
                  className={zoneMode === "work-areas" ? "btn btn-primary" : "btn"}
                  disabled={inProgress}
                  onClick={() => setZoneMode("work-areas")}
                >
                  등록된 작업구역에서 고르기
                </button>
                <button
                  type="button"
                  className={zoneMode === "draw" ? "btn btn-primary" : "btn"}
                  disabled={inProgress}
                  onClick={() => setZoneMode("draw")}
                >
                  지도에 즉석으로 그리기
                </button>
              </div>
            )}

            {zoneMode === "work-areas" ? (
              <div className="flex flex-col gap-2">
                <p className="text-[12.5px] break-keep text-ink-muted">
                  <strong className="font-bold">권장</strong> — 등록된 작업구역을 고르면 다음
                  비행의 결과와 자동으로 이어져{" "}
                  <Link
                    href={`/sites/${encodeURIComponent(siteId)}/progress`}
                    className="font-semibold text-accent-text hover:underline"
                  >
                    계획 대비 진척
                  </Link>
                  을 계산할 수 있습니다. 즉석 폴리곤은 매번 범위가 달라 진척으로
                  이어지지 않습니다.
                </p>
                {workAreas.length === 0 ? (
                  <p className="text-[12.5px] break-keep text-ink-muted">
                    이 현장에는 등록된 작업구역이 없습니다.{" "}
                    <Link
                      href={`/sites/${encodeURIComponent(siteId)}/work-areas`}
                      className="font-semibold text-accent-text hover:underline"
                    >
                      작업구역 등록하기
                    </Link>
                  </p>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {workAreas.map((area) => (
                      <li key={area.workAreaId}>
                        <label className="flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-2 text-[12.5px] break-keep">
                          <input
                            type="checkbox"
                            checked={selectedWorkAreaIds.includes(area.workAreaId)}
                            disabled={inProgress}
                            onChange={(event) => {
                              setSelectedWorkAreaIds((prev) =>
                                event.target.checked
                                  ? [...prev, area.workAreaId]
                                  : prev.filter((id) => id !== area.workAreaId),
                              );
                              setError(null);
                            }}
                          />
                          <span className="font-semibold">{area.name}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <>
                <p className="text-[12.5px] break-keep text-ink-muted">
                  {siteAoi
                    ? "현장 경계를 초기값으로 표시했습니다 — 그대로 쓰거나 지도에서 고쳐 그린 뒤 확정하세요."
                    : "이 현장은 경계가 설정돼 있지 않습니다 — 지도에서 구역을 직접 그린 뒤 확정하세요."}{" "}
                  이 범위는 <strong className="font-bold">이번 한 번만</strong> 쓰입니다 —
                  다음 비행 결과와 이어 진척을 보려면 위에서 등록된 작업구역을 고르세요.
                </p>
                <AoiPolygonMap
                  value={vertices}
                  onChange={(next) => {
                    setVertices(next);
                    setZonesConfirmed(false);
                  }}
                  readOnly={inProgress}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="btn w-fit"
                    disabled={vertices.length < 3 || zonesConfirmed || inProgress}
                    onClick={() => setZonesConfirmed(true)}
                  >
                    이 구역으로 확정
                  </button>
                  <span
                    className={
                      zonesConfirmed
                        ? "text-[12.5px] break-keep text-safe-ink"
                        : "text-[12.5px] break-keep text-ink-muted"
                    }
                  >
                    {zonesConfirmed
                      ? "구역 확정됨 — 이 범위 안의 잔량을 계산합니다."
                      : vertices.length < 3
                        ? "꼭짓점을 3개 이상 찍어야 구역이 됩니다."
                        : "아직 확정 전입니다."}
                  </span>
                </div>
              </>
            )}
          </div>

          {!inProgress && (
            <button
              type="button"
              className="btn btn-primary w-fit"
              disabled={!canSubmit}
              onClick={() => void handleSubmit()}
            >
              {submitting ? "제출하는 중…" : "잔량 계산 요청"}
            </button>
          )}
        </>
      )}

      {request && (
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge
              label={PROCESSING_JOB_STATUS_LABEL[request.status]?.label ?? request.status}
              tone={PROCESSING_JOB_STATUS_LABEL[request.status]?.tone ?? "neutral"}
            />
            <span className="num text-[11.5px] break-token text-ink-muted">
              {request.requestId}
            </span>
          </div>

          {inProgress && (
            <p className="text-[12.5px] break-keep text-ink-muted">
              잔량을 계산하는 중입니다 — 자료 크기에 따라 수 분 걸릴 수 있습니다. 이
              화면을 열어두지 않아도 됩니다(다시 방문하면 이어서 보여줍니다).
            </p>
          )}

          {request.status === "FAILED" && (
            <p className="text-[12.5px] break-keep text-crit-ink">
              계산에 실패했습니다{request.detail ? ` — ${request.detail}` : "."}
            </p>
          )}

          {request.status === "SUCCEEDED" && initialReport === null && (
            <p className="text-[12.5px] break-keep text-ink-muted">
              계산이 끝났습니다 — 결과를 불러오는 중입니다.
            </p>
          )}
        </div>
      )}

      {initialReport && (
        <ConformanceResult
          missionId={missionId}
          siteId={siteId}
          canIssue={canIssue}
          entry={initialReport}
          totalNetM3={initialTotalNetM3}
        />
      )}
    </section>
  );
}
