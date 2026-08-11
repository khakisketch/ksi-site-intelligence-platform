"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { PROCESSING_JOB_STATUS_LABEL } from "@/app/missions/mission-labels";
import { readableApiError } from "@/lib/core-api/labels";
import {
  canSubmitComparison,
  comparisonEligibility,
  currentMissionEpochs,
  isTerminalComparisonStatus,
  selectableEpochs,
  toZonesPayload,
  type ComparisonEpoch,
} from "@/lib/comparison-submit";
import type {
  AoiVertex,
  ComparisonPolicyView,
  ComparisonRequestContract,
  ComparisonRequestDetailView,
  ComparisonRequestMutationResponse,
  SiteProcessingJobSummary,
} from "@/lib/core-api/types";

const POLL_INTERVAL_MS = 5000;

async function parseJsonSafe<T>(response: Response): Promise<Partial<T>> {
  try {
    return (await response.json()) as T;
  } catch {
    return {};
  }
}

function formatEpoch(epoch: ComparisonEpoch): string {
  const when = new Date(epoch.issuedAt);
  const stamp = Number.isNaN(when.getTime())
    ? epoch.issuedAt
    : when.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
  return `${stamp} · ${epoch.jobId}`;
}

/** 산출물 보유 여부를 사람 말로 — 제출 전에 무엇을 잴 수 있는지 보이게 한다. */
function EpochArtifactBadges({ epoch }: { epoch: ComparisonEpoch }) {
  return (
    <span className="flex flex-wrap gap-1">
      <span
        className={`inline-flex items-center rounded-full border px-1.5 text-[10.5px] whitespace-nowrap ${
          epoch.hasPointCloud
            ? "border-safe text-safe-ink"
            : "border-line-strong text-ink-muted"
        }`}
      >
        점군 {epoch.hasPointCloud ? "있음" : "없음"}
      </span>
      <span
        className={`inline-flex items-center rounded-full border px-1.5 text-[10.5px] whitespace-nowrap ${
          epoch.hasDsm ? "border-safe text-safe-ink" : "border-line-strong text-ink-muted"
        }`}
      >
        높이자료 {epoch.hasDsm ? "있음" : "없음"}
      </span>
    </span>
  );
}

/**
 * 두 시점 비교 제출 — 완료된 재구성 두 개를 골라 "비교하라"고 지시한다(W2-3).
 *
 * 계산은 워커가 한다(사람이 결과 숫자를 손으로 주장할 수 없다는 설계) — 이
 * 화면은 **무엇과 무엇을, 어느 구역에서** 비교할지만 정해 요청을 만든다.
 *
 * ## 구역은 자동으로 확정되지 않는다 (대표자 확정, 2026-08-10)
 *
 * 현장 경계를 지도에 **초기값으로만** 띄우고, 사용자가 확인·수정한 뒤 명시적으로
 * 확정해야 제출에 실린다. 확정하지 않으면 `zones` 없이 제출되고 부피 비교는
 * 시도되지 않는다 — 조용히 현장 경계를 써 버리면 사용자는 어느 범위로 쟀는지
 * 모른 채 숫자를 받는다.
 *
 * ## 기준값은 서버가 내려준 것을 그대로 보여준다
 *
 * 화면이 숫자를 갖고 있지 않다(`policy` prop) — 계산 쪽이 바뀌어도 화면이 옛
 * 숫자를 말하는 일이 구조적으로 생기지 않는다. 사용자가 바꾸는 입력은 없다.
 *
 * ## 폴링 관용구는 SourceUploadPanel 것을 그대로 따른다
 *
 * 재귀 `setTimeout` + ref 간접참조 + "id 가 바뀌는 것 자체가 effect 를
 * 트리거"하는 단일 경로 — 그 파일이 누수 수정으로 도달한 형태다(직접 폴링을
 * 시작하면 unmount 시 타이머 체인이 정리되지 않는다).
 */
export function ComparisonSubmitPanel({
  missionId,
  canIssue,
  siteJobs,
  siteAoi,
  policy,
  initialRequest,
}: {
  missionId: string;
  canIssue: boolean;
  siteJobs: SiteProcessingJobSummary[];
  /** 현장 경계 — **초기값으로만** 쓴다(자동 확정하지 않는다). 없으면 직접 그린다. */
  siteAoi: AoiVertex[] | null;
  /** 서버가 내려준 고정 기준값. 조회 실패 시 null — 그때는 값을 지어내지 않는다. */
  policy: ComparisonPolicyView | null;
  /** 새로고침 복원용 — 그 임무의 최신 비교 요청(없으면 null). */
  initialRequest: ComparisonRequestContract | null;
}) {
  const epochs = useMemo(() => selectableEpochs(siteJobs), [siteJobs]);
  // "비교 시점(이후)" 후보는 이 임무가 만든 재구성으로 좁힌다 — 서버가
  // currentJobId 에 요구하는 소속 제약과 같다(comparison-submit.ts 함수 docstring).
  const currentEpochs = useMemo(
    () => currentMissionEpochs(epochs, missionId),
    [epochs, missionId],
  );

  const [baselineJobId, setBaselineJobId] = useState<string>("");
  const [currentJobId, setCurrentJobId] = useState<string>("");
  const [vertices, setVertices] = useState<AoiVertex[]>(siteAoi ?? []);
  const [zonesConfirmed, setZonesConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [request, setRequest] = useState<ComparisonRequestContract | null>(initialRequest);

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollRef = useRef<(id: string) => Promise<void>>(async () => {});

  const baseline = epochs.find((e) => e.jobId === baselineJobId) ?? null;
  const current = epochs.find((e) => e.jobId === currentJobId) ?? null;
  const eligibility = comparisonEligibility(baseline, current, zonesConfirmed);

  const poll = useCallback(async (id: string) => {
    try {
      const response = await fetch(`/api/comparison-requests/${encodeURIComponent(id)}`);
      if (response.ok) {
        const body = await parseJsonSafe<ComparisonRequestDetailView>(response);
        if (body.request) {
          setRequest(body.request);
          if (isTerminalComparisonStatus(body.request.status)) return;
        }
      }
    } catch {
      // 일시 네트워크 오류 — 폴링을 멈추지 않고 다음 tick 에 재시도한다.
    }
    pollTimer.current = setTimeout(() => void pollRef.current(id), POLL_INTERVAL_MS);
  }, []);

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  // 진행 중인 요청이 있을 때만 폴링한다. requestId 가 바뀌는 것 자체가 이
  // effect 를 재실행시키므로 모든 폴링 시작이 cleanup 을 갖는다(모듈 docstring).
  const pendingRequestId =
    request !== null && !isTerminalComparisonStatus(request.status) ? request.requestId : null;
  useEffect(() => {
    if (!pendingRequestId) return undefined;
    const kickoff = setTimeout(() => void pollRef.current(pendingRequestId), 0);
    return () => {
      clearTimeout(kickoff);
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [pendingRequestId]);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const zonePayload = zonesConfirmed ? toZonesPayload(vertices) : null;
      const response = await fetch(
        `/api/missions/${encodeURIComponent(missionId)}/comparison-requests`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            baselineJobId,
            currentJobId,
            zones: zonePayload?.zones ?? null,
            zoneCrs: zonePayload?.zoneCrs ?? null,
          }),
        },
      );
      const body = await parseJsonSafe<ComparisonRequestMutationResponse>(response);
      if (!response.ok || !body.request) {
        setError(readableApiError(body, "비교 요청 제출에 실패했습니다"));
        return;
      }
      // 같은 조합의 재요청은 기존 요청을 그대로 돌려준다(ALREADY_REQUESTED) —
      // 오류가 아니라 재사용이므로 그 요청의 상태를 이어서 보여준다.
      setRequest(body.request);
    } catch {
      setError("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!canIssue) {
    return (
      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
        <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
          두 시점 비교
        </h3>
        <p className="text-[12.5px] break-keep text-ink-muted">
          비교를 요청하려면 임무 발급 권한(MISSIONS_ISSUE)이 필요합니다.
        </p>
      </section>
    );
  }

  const status = request?.status ?? null;
  const inProgress = status !== null && !isTerminalComparisonStatus(status);

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
          두 시점 비교
        </h3>
        <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
          비교 가능한 결과 {epochs.length}건
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

      {epochs.length < 2 ? (
        <p className="text-[12.5px] break-keep text-ink-muted">
          비교하려면 이 현장에서 완료된 재구성이 두 개 이상 있어야 합니다 — 지금은{" "}
          {epochs.length}건입니다. 같은 구역을 다른 시점에 한 번 더 촬영·재구성한 뒤
          다시 오세요.
        </p>
      ) : currentEpochs.length === 0 ? (
        <p className="text-[12.5px] break-keep text-ink-muted">
          이 임무에서 만든 재구성이 아직 없어 여기서는 비교를 시작할 수 없습니다 —
          비교는 항상 그 결과를 만든 임무 화면에서 시작합니다. 이 현장의 다른
          재구성이 완료된 임무 화면으로 가서 다시 시도하세요.
        </p>
      ) : (
        <>
          {/* ── 두 시점 선택 + 방향 명시 ───────────────────────────────── */}
          <div className="flex flex-col gap-3 sm:flex-row sm:gap-4">
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-[11.5px] break-keep text-ink-muted">
                기준 시점(이전)
              </span>
              <select
                className="input"
                value={baselineJobId}
                disabled={inProgress}
                onChange={(e) => {
                  setBaselineJobId(e.target.value);
                  setError(null);
                }}
              >
                <option value="">고르세요</option>
                {epochs.map((e) => (
                  <option key={e.jobId} value={e.jobId}>
                    {formatEpoch(e)}
                  </option>
                ))}
              </select>
              {baseline && <EpochArtifactBadges epoch={baseline} />}
            </label>

            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-[11.5px] break-keep text-ink-muted">
                비교 시점(이후) · 이 임무의 결과만
              </span>
              <select
                className="input"
                value={currentJobId}
                disabled={inProgress}
                onChange={(e) => {
                  setCurrentJobId(e.target.value);
                  setError(null);
                }}
              >
                <option value="">고르세요</option>
                {currentEpochs.map((e) => (
                  <option key={e.jobId} value={e.jobId}>
                    {formatEpoch(e)}
                  </option>
                ))}
              </select>
              {current && <EpochArtifactBadges epoch={current} />}
            </label>
          </div>

          {baseline && current && baseline.jobId !== current.jobId && (
            <p className="rounded-md bg-sunk px-3 py-2 text-[12.5px] break-keep text-ink-2">
              <strong>{formatEpoch(baseline)}</strong> 을(를) 기준으로{" "}
              <strong>{formatEpoch(current)}</strong> 에서 무엇이 달라졌는지 잽니다.
            </p>
          )}

          {/* ── 구역 확인·수정·확정 ───────────────────────────────────── */}
          <div className="flex flex-col gap-2 border-t border-line pt-3">
            <p className="text-[12.5px] break-keep text-ink-muted">
              {siteAoi
                ? "현장 경계를 초기값으로 표시했습니다 — 그대로 쓰거나 지도에서 고쳐 그린 뒤 확정하세요."
                : "이 현장은 경계가 설정돼 있지 않습니다 — 부피를 재려면 지도에서 구역을 직접 그린 뒤 확정하세요."}
              {" 확정하지 않으면 부피 비교 없이 변화만 비교합니다."}
            </p>
            <AoiPolygonMap
              value={vertices}
              onChange={(next) => {
                setVertices(next);
                // 도형이 바뀌면 확정은 풀린다 — 확정 이후 조용히 다른 구역이
                // 제출되는 일이 없게 한다.
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
              {zonesConfirmed ? (
                <span className="text-[12.5px] break-keep text-safe-ink">
                  구역 확정됨 — 부피 비교도 함께 요청합니다.
                </span>
              ) : (
                <span className="text-[12.5px] break-keep text-ink-muted">
                  {vertices.length < 3
                    ? "꼭짓점을 3개 이상 찍어야 구역이 됩니다."
                    : "아직 확정 전입니다."}
                </span>
              )}
            </div>
          </div>

          {/* ── 쓰게 될 기준값(읽기 전용) ─────────────────────────────── */}
          <div className="flex flex-col gap-1 border-t border-line pt-3">
            <h4 className="text-[11.5px] font-bold break-keep text-ink-2">
              이번 비교에 쓰는 기준 (고정값 · 바꿀 수 없음)
            </h4>
            {policy ? (
              <dl className="grid grid-cols-1 gap-1 text-[12.5px] sm:grid-cols-3">
                <div className="flex justify-between gap-2 sm:flex-col sm:justify-start">
                  <dt className="break-keep text-ink-muted">움직임으로 칠 최소 거리</dt>
                  <dd className="num">{policy.distanceThresholdM} m</dd>
                </div>
                <div className="flex justify-between gap-2 sm:flex-col sm:justify-start">
                  <dt className="break-keep text-ink-muted">재촬영 권고 비율</dt>
                  <dd className="num">
                    {(policy.revisitRatioThreshold * 100).toFixed(1)} %
                  </dd>
                </div>
                <div className="flex justify-between gap-2 sm:flex-col sm:justify-start">
                  <dt className="break-keep text-ink-muted">기준 묶음</dt>
                  <dd className="num break-token">{policy.policyVersion}</dd>
                </div>
              </dl>
            ) : (
              <p className="text-[12.5px] break-keep text-ink-muted">
                기준값을 불러오지 못했습니다 — 제출은 가능하지만, 어떤 기준으로
                계산되는지는 결과 화면에서 확인하세요.
              </p>
            )}
          </div>

          {/* ── 제출 ──────────────────────────────────────────────────── */}
          {!inProgress && (
            <div className="flex flex-col gap-2">
              {eligibility.blockedReason && (
                <p className="text-[12.5px] break-keep text-ink-muted">
                  {eligibility.blockedReason}
                </p>
              )}
              {!eligibility.blockedReason && (
                <p className="text-[12.5px] break-keep text-ink-muted">
                  요청할 비교: {eligibility.changeDetection ? "변화(점군)" : null}
                  {eligibility.changeDetection && eligibility.volumeChange ? " · " : null}
                  {eligibility.volumeChange ? "부피(높이자료)" : null}
                </p>
              )}
              <button
                type="button"
                className="btn btn-primary w-fit"
                disabled={!canSubmitComparison(eligibility) || submitting}
                onClick={() => void handleSubmit()}
              >
                {submitting ? "제출하는 중…" : "비교 요청 제출"}
              </button>
            </div>
          )}

          {/* ── 진행 상태 ─────────────────────────────────────────────── */}
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
                  비교를 계산하는 중입니다 — 자료 크기에 따라 수 분 걸릴 수 있습니다.
                  이 화면을 열어두지 않아도 됩니다(다시 방문하면 이어서 보여줍니다).
                </p>
              )}

              {request.status === "SUCCEEDED" && (
                <>
                  <p className="text-[12.5px] break-keep text-safe-ink">
                    비교가 완료되었습니다.
                  </p>
                  <Link
                    href={`/reports?missionId=${encodeURIComponent(request.missionId)}`}
                    className="btn btn-primary w-fit"
                  >
                    결과 보기
                  </Link>
                </>
              )}

              {request.status === "FAILED" && (
                <>
                  <p className="text-[12.5px] break-keep text-crit-ink">
                    비교에 실패했습니다{request.detail ? ` — ${request.detail}` : "."}
                  </p>
                  <p className="text-[12.5px] break-keep text-ink-muted">
                    구역이나 시점을 바꿔 다시 요청할 수 있습니다. 같은 조합 그대로
                    다시 제출하면 이미 있는 요청이 그대로 유지됩니다(중복이 생기지
                    않습니다).
                  </p>
                </>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
