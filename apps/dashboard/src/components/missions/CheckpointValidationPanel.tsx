"use client";

import { useMemo, useRef, useState } from "react";

import { StatusBadge } from "@/components/ui/StatusBadge";
import { usePolling } from "@/hooks/usePolling";
import { readableApiError } from "@/lib/core-api/labels";
import { parseJsonSafe } from "@/lib/http";
import { formatKoreanDateTime } from "@/lib/datetime";
import type {
  CheckpointValidationMutationResponse,
  CheckpointValidationRegisterInput,
  CheckpointValidationRegisterResponse,
  CheckpointValidationView,
  SiteProcessingJobSummary,
} from "@/lib/core-api/types";

const CHECKPOINT_VALIDATION_ENABLED =
  process.env.NEXT_PUBLIC_KSI_CHECKPOINT_VALIDATION_ENABLED === "1";
const MAX_CSV_BYTES = 5 * 1024 * 1024;

type ValidationEpoch = {
  jobId: string;
  missionId: string;
  issuedAt: string;
  artifactId: string;
};

/** Only successful epochs with a concrete DSM can receive a validation CSV. */
export function selectableCheckpointEpochs(
  jobs: readonly SiteProcessingJobSummary[],
): ValidationEpoch[] {
  return jobs
    .filter((job) => job.status === "SUCCEEDED")
    .flatMap((job) =>
      job.artifacts
        .filter((artifact) => artifact.kind === "dsm")
        .map((artifact) => ({
          jobId: job.jobId,
          missionId: job.missionId,
          issuedAt: job.issuedAt,
          artifactId: artifact.artifactId,
        })),
    )
    .sort((a, b) => b.issuedAt.localeCompare(a.issuedAt));
}

export function isTerminalCheckpointValidation(status: string): boolean {
  return status === "VALIDATED" || status === "REJECTED";
}

export function shouldPollCheckpointValidation(status: string): boolean {
  return status === "SEALED";
}

function statusAppearance(status: string): { label: string; tone: "neutral" | "progress" | "positive" | "warning" } {
  switch (status) {
    case "REGISTERED":
      return { label: "등록됨", tone: "neutral" };
    case "SEALED":
      return { label: "측정 대기", tone: "progress" };
    case "VALIDATED":
      return { label: "서버 검증 완료", tone: "positive" };
    case "REJECTED":
      return { label: "검증 거부", tone: "warning" };
    default:
      return { label: status, tone: "neutral" };
  }
}

export function checkpointNextAction(validation: CheckpointValidationView): string {
  switch (validation.status) {
    case "REGISTERED":
      return "CSV 원본을 올린 뒤 봉인해야 서버 측정이 시작됩니다.";
    case "SEALED":
      return "서버가 봉인된 CSV와 DSM을 읽어 잔차를 계산 중입니다.";
    case "VALIDATED":
      return "이 DSM 시점의 서버 측정값이 원장에 고정되었습니다. 두 시점 모두 검증되면 비교 불확실성 계산에 사용할 수 있습니다.";
    case "REJECTED":
      return "거부 사유를 바로잡은 새 CSV로 다시 등록하세요. 기존 검증 원장은 바뀌지 않습니다.";
    default:
      return "상태를 다시 확인하세요.";
  }
}

function formatMeters(value: number): string {
  return `${value.toFixed(3)} m`;
}

async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function validationEpochLabel(epoch: ValidationEpoch): string {
  return `${formatKoreanDateTime(epoch.issuedAt, { dateStyle: "medium", timeStyle: "short" })} · ${epoch.jobId}`;
}

/**
 * 선택적으로 독립 검사점 CSV를 봉인하고 DSM에 대해 서버 측정을 요청한다.
 *
 * 이 카드에는 RMSE 입력이 없다. 사용자가 제출하는 것은 CSV bytes, 좌표/수직
 * 기준과 독립성 선언뿐이며, 수치는 sealed bytes를 직접 읽는 worker만 만든다.
 */
export function CheckpointValidationPanel({
  canWrite,
  siteJobs,
  initialValidations,
}: {
  canWrite: boolean;
  siteJobs: SiteProcessingJobSummary[];
  /** jobId별 조회 이력. 조회 실패한 job은 빈 배열로 내려도 카드가 막히지 않는다. */
  initialValidations: CheckpointValidationView[];
}) {
  const epochs = useMemo(() => selectableCheckpointEpochs(siteJobs), [siteJobs]);
  const [epochKey, setEpochKey] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [crs, setCrs] = useState("");
  const [verticalDatum, setVerticalDatum] = useState("");
  const [verticalBasis, setVerticalBasis] = useState("");
  const [independent, setIndependent] = useState(false);
  const [independenceBasis, setIndependenceBasis] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latest, setLatest] = useState<CheckpointValidationView | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const selectedEpoch = epochs.find((epoch) => `${epoch.jobId}:${epoch.artifactId}` === epochKey) ?? null;
  const activeValidation = latest;
  // REGISTERED may be waiting for a browser upload or retry; polling only
  // begins after seal, when a worker can actually advance the record.
  const pendingValidationId =
    activeValidation && shouldPollCheckpointValidation(activeValidation.status)
      ? activeValidation.validationId
      : null;
  const mutationAllowed = CHECKPOINT_VALIDATION_ENABLED && canWrite;

  usePolling(
    pendingValidationId,
    async (validationId) => {
      const response = await fetch(`/api/checkpoint-validations/${encodeURIComponent(validationId)}`);
      if (!response.ok) return null;
      const body = await parseJsonSafe<CheckpointValidationMutationResponse>(response);
      return body.validation ?? null;
    },
    (validation) => isTerminalCheckpointValidation(validation.status),
    (validation) => setLatest(validation),
  );

  async function submit(): Promise<void> {
    setError(null);
    if (!selectedEpoch || !file) {
      setError("검증할 DSM 시점과 검사점 CSV 파일을 선택하세요.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setError("검사점 v1 입력은 .csv 파일만 허용합니다.");
      return;
    }
    if (file.size < 1 || file.size > MAX_CSV_BYTES) {
      setError("검사점 CSV는 비어 있지 않고 5 MiB 이하여야 합니다.");
      return;
    }
    if (!crs.trim() || !verticalDatum || !verticalBasis.trim() || !independenceBasis.trim() || !independent) {
      setError("CRS·수직기준·독립성 근거를 모두 입력하고 독립 검사점 선언을 확인하세요.");
      return;
    }

    setSubmitting(true);
    try {
      const input: CheckpointValidationRegisterInput = {
        filename: file.name,
        sha256: await sha256Hex(file),
        sizeBytes: file.size,
        crs: crs.trim(),
        verticalReference: {
          datum: verticalDatum as CheckpointValidationRegisterInput["verticalReference"]["datum"],
          basis: verticalBasis.trim(),
          source: "user_declared",
        },
        independentFromProcessingAttested: true,
        independenceBasis: independenceBasis.trim(),
      };
      const registerResponse = await fetch(
        `/api/processing-jobs/${encodeURIComponent(selectedEpoch.jobId)}/artifacts/${encodeURIComponent(selectedEpoch.artifactId)}/checkpoint-validations`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        },
      );
      const registered = await parseJsonSafe<CheckpointValidationRegisterResponse>(registerResponse);
      if (!registerResponse.ok || !registered.validation || !registered.uploadUrl) {
        setError(readableApiError(registered, "검사점 CSV 등록에 실패했습니다."));
        return;
      }

      // Core가 발급한 URL로만 올리고, Dashboard 서버는 raw checkpoint bytes를 보관하지 않는다.
      const put = await fetch(registered.uploadUrl, {
        method: "PUT",
        headers: { "Content-Type": "text/csv" },
        body: file,
      });
      if (!put.ok) {
        setLatest(registered.validation);
        setError("검사점 CSV 스토리지 업로드에 실패했습니다. 파일을 확인한 뒤 같은 입력으로 다시 시도하세요.");
        return;
      }

      const sealResponse = await fetch(
        `/api/checkpoint-validations/${encodeURIComponent(registered.validation.validationId)}/seal`,
        { method: "POST" },
      );
      const sealed = await parseJsonSafe<CheckpointValidationMutationResponse>(sealResponse);
      if (!sealResponse.ok || !sealed.validation) {
        setLatest(registered.validation);
        setError(readableApiError(sealed, "검사점 CSV 봉인에 실패했습니다."));
        return;
      }
      setLatest(sealed.validation);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch {
      setError("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
    } finally {
      setSubmitting(false);
    }
  }

  // Latest comes first so a freshly polled projection replaces the same
  // validationId from the server-rendered snapshot.
  const validations = [...(latest ? [latest] : []), ...initialValidations].filter(
    (validation, index, all) => all.findIndex((item) => item.validationId === validation.validationId) === index,
  );

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">독립 검사점 검증 (선택)</h3>
        <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
          DSM 시점 {epochs.length}건 · 검증 이력 {validations.length}건
        </span>
      </div>

      <p className="text-[12.5px] break-keep text-ink-muted">
        외부 측량으로 확보한 검사점 CSV를 봉인해 DSM과 서버에서 직접 대조합니다. RMSE를 입력하거나
        수정할 수 없으며, 결과는 운영관리용 상대 물량의 불확실성 근거일 뿐 계약 정산·측량급 정확도
        주장은 아닙니다.
      </p>

      {!CHECKPOINT_VALIDATION_ENABLED && (
        <p className="rounded-md bg-sunk px-3 py-2 text-[12.5px] break-keep text-ink-2">
          새 검사점 검증 등록은 현재 읽기 전용입니다. 기존 검증 이력은 계속 확인할 수 있습니다.
        </p>
      )}

      {!canWrite && CHECKPOINT_VALIDATION_ENABLED && (
        <p className="text-[12.5px] break-keep text-ink-muted">
          검사점 검증을 등록하려면 현장 등록 권한(SITES_WRITE)이 필요합니다.
        </p>
      )}

      {error && (
        <p role="alert" className="rounded-md bg-crit-bg px-3 py-2 text-[12.5px] font-semibold break-keep text-crit-ink">
          {error}
        </p>
      )}

      {epochs.length === 0 ? (
        <p className="text-[12.5px] break-keep text-ink-muted">
          완료되고 DSM 산출물이 등록된 재구성 시점이 생기면 여기서 검증할 수 있습니다.
        </p>
      ) : mutationAllowed ? (
        <div className="flex flex-col gap-3 border-t border-line pt-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-[12.5px] font-semibold text-ink-2">
              DSM 시점
              <select
                value={epochKey}
                onChange={(event) => setEpochKey(event.target.value)}
                disabled={submitting}
                className="min-h-10 rounded-md border border-line-strong bg-surface px-2 text-[13px] font-normal text-ink-1"
              >
                <option value="">선택하세요</option>
                {epochs.map((epoch) => (
                  <option key={`${epoch.jobId}:${epoch.artifactId}`} value={`${epoch.jobId}:${epoch.artifactId}`}>
                    {validationEpochLabel(epoch)}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-[12.5px] font-semibold text-ink-2">
              검사점 CSV
              <input
                ref={fileInputRef}
                type="file"
                accept="text/csv,.csv"
                disabled={submitting}
                className="min-h-10 rounded-md border border-line-strong bg-surface px-2 py-1 text-[12.5px] font-normal text-ink-1 file:mr-3 file:rounded file:border-0 file:bg-sunk file:px-2 file:py-1 file:text-[12px] file:font-semibold"
                aria-describedby="checkpoint-csv-format"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
          </div>
          <p id="checkpoint-csv-format" className="text-[11.5px] break-keep text-ink-muted">
            UTF-8 CSV 열 순서: <code>checkpoint_id,easting_m,northing_m,elevation_m</code> · 최대 10,000점 / 5 MiB.
          </p>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-[12.5px] font-semibold text-ink-2">
              검사점 CRS
              <input
                value={crs}
                onChange={(event) => setCrs(event.target.value)}
                disabled={submitting}
                placeholder="예: EPSG:5186"
                className="min-h-10 rounded-md border border-line-strong bg-surface px-2 text-[13px] font-normal text-ink-1"
              />
            </label>
            <label className="flex flex-col gap-1 text-[12.5px] font-semibold text-ink-2">
              수직 기준 종류
              <select
                value={verticalDatum}
                onChange={(event) => setVerticalDatum(event.target.value)}
                disabled={submitting}
                className="min-h-10 rounded-md border border-line-strong bg-surface px-2 text-[13px] font-normal text-ink-1"
              >
                <option value="">선택하세요</option>
                <option value="ellipsoidal">타원체고</option>
                <option value="ellipsoidal_native">원본 타원체고</option>
                <option value="orthometric_kngeoid2018">정표고 (KNGeoid18)</option>
                <option value="orthometric_kngeoid2024">정표고 (KNGeoid24)</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[12.5px] font-semibold text-ink-2 sm:col-span-2">
              수직 기준 근거
              <input
                value={verticalBasis}
                onChange={(event) => setVerticalBasis(event.target.value)}
                disabled={submitting}
                placeholder="예: 2026-08-29 현장 측량 성과, KNGeoid24 적용"
                maxLength={1000}
                className="min-h-10 rounded-md border border-line-strong bg-surface px-2 text-[13px] font-normal text-ink-1"
              />
            </label>
          </div>

          <label className="flex items-start gap-2 rounded-md border border-line p-3 text-[12.5px] break-keep text-ink-2">
            <input
              type="checkbox"
              checked={independent}
              onChange={(event) => setIndependent(event.target.checked)}
              disabled={submitting}
              className="mt-0.5 size-4"
            />
            <span>이 검사점은 이 재구성에 사용한 GCP·사진 위치·처리 결과와 독립적임을 확인합니다.</span>
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] font-semibold text-ink-2">
            독립성 근거
            <textarea
              value={independenceBasis}
              onChange={(event) => setIndependenceBasis(event.target.value)}
              disabled={submitting}
              rows={2}
              placeholder="예: 별도 측량팀이 재구성 입력과 분리된 기준점으로 측정"
              maxLength={1000}
              className="rounded-md border border-line-strong bg-surface px-2 py-2 text-[13px] font-normal text-ink-1"
            />
          </label>
          <button type="button" className="btn btn-primary w-fit" disabled={submitting} onClick={() => void submit()}>
            {submitting ? "CSV 등록·봉인 중…" : "독립 검사점 검증 시작"}
          </button>
        </div>
      ) : null}

      {validations.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <h4 className="text-[12.5px] font-bold break-keep text-ink-2">검증 이력</h4>
          <ul className="flex flex-col gap-2">
            {validations.map((validation) => {
              const appearance = statusAppearance(validation.status);
              return (
                <li key={validation.validationId} className="rounded-md border border-line bg-sunk p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <StatusBadge label={appearance.label} tone={appearance.tone} />
                    <span className="num text-[11px] break-token text-ink-muted">{validation.validationId}</span>
                  </div>
                  <p className="mt-2 text-[12px] break-keep text-ink-muted">
                    DSM {validation.dsm.jobId} · {validation.declared.filename} · 등록 {formatKoreanDateTime(validation.registeredAt, { dateStyle: "medium", timeStyle: "short" })}
                  </p>
                  {validation.observed && (
                    <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] sm:grid-cols-4">
                      <Metric label="유효 점" value={`${validation.observed.pointCount}점`} />
                      <Metric label="RMSE" value={formatMeters(validation.observed.rmseM)} />
                      <Metric label="MAE" value={formatMeters(validation.observed.maeM)} />
                      <Metric label="최대 절대오차" value={formatMeters(validation.observed.maxAbsErrorM)} />
                    </dl>
                  )}
                  {validation.status === "REJECTED" && (
                    <p className="mt-2 text-[12px] break-keep text-crit-ink">
                      {validation.rejectionReason ?? "검증 거부"}
                      {validation.rejectionDetail ? ` · ${validation.rejectionDetail}` : ""}
                    </p>
                  )}
                  <p className="mt-2 text-[12px] break-keep text-ink-2">다음 행동: {checkpointNextAction(validation)}</p>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="num font-semibold text-ink-2">{value}</dd>
    </div>
  );
}
