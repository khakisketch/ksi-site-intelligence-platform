"use client";

import Link from "next/link";
import { useState } from "react";

import {
  assignUniqueMediaIds,
  buildSourceMediaClaim,
  canReissueProcessingJob,
  chunk,
  isTerminalJobStatus,
  summarizeUploadBatch,
} from "@/lib/source-upload";
import { API_ERROR_MESSAGE, readableApiError } from "@/lib/core-api/labels";
import { parseJsonSafe } from "@/lib/http";
import { usePolling } from "@/hooks/usePolling";
import { PROCESSING_JOB_STATUS_LABEL } from "@/app/missions/mission-labels";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type {
  ProcessingArtifactSummary,
  ProcessingJobArtifactsView,
  ProcessingJobIssueInput,
  ProcessingJobMutationResponse,
  SourceMediaBatchResponse,
  SourceMediaBundleView,
  SourceMediaFileClaim,
  SourceMediaSealResponse,
} from "@/lib/core-api/types";

// 서버 배치 상한(MAX_BATCH_SIZE=200) 아래로 여유있게 — 요청 1건 실패가 미치는
// 범위를 줄인다(source_media.py 모듈 docstring: "한 요청당 상한").
const BATCH_SIZE = 50;

/**
 * 사용자는 엔진 이미지·파라미터를 고르지 않는다. Core registry가 이 불변 ID를
 * canonical profile snapshot으로 확장한다(REQ-INT-104). Dashboard와 로컬
 * 업로더가 각자 ODM 값을 복제하면 같은 현장의 두 epoch가 조용히 달라질 수 있다.
 */
const KSI_STANDARD_PROCESSING_PROFILE_ID = "ksi-odm-civil-v1";
const RECONSTRUCTION_SPEC: ProcessingJobIssueInput = {
  processingProfileId: KSI_STANDARD_PROCESSING_PROFILE_ID,
};

type FileStatus = "pending" | "registering" | "uploading" | "done" | "error";

interface UploadItem {
  file: File;
  mediaId: string;
  status: FileStatus;
  message?: string;
}

type Phase =
  | "idle"
  | "uploading"
  | "ready-to-seal"
  | "sealing"
  | "sealed"
  | "issuing"
  | "job-running"
  | "job-done"
  | "job-failed";

function readableError(code: string | undefined, fallback: string): string {
  if (code && code in API_ERROR_MESSAGE) return API_ERROR_MESSAGE[code as keyof typeof API_ERROR_MESSAGE];
  return fallback;
}

const FILE_STATUS_LABEL: Record<FileStatus, string> = {
  pending: "대기",
  registering: "등록 중…",
  uploading: "올리는 중…",
  done: "완료",
  error: "실패",
};

/**
 * 사진 업로드 → 번들 봉인 → 재구성 발행 → 상태 폴링(M3, B1/B2).
 *
 * 파일 바이트는 대시보드 서버를 거치지 않는다 — presigned URL 로 브라우저가
 * 스토리지에 직접 PUT 한다(EvidencePanel 과 동일 원칙, ADR-KSI-010 §1).
 */
export function SourceUploadPanel({
  missionId,
  canIssue,
  initialBundle,
  initialJob,
  hasComparisonReport,
}: {
  missionId: string;
  canIssue: boolean;
  initialBundle: SourceMediaBundleView | null;
  initialJob: { jobId: string; status: string; detail?: string | null } | null;
  /** change-detection·volume-change 둘 다 없으면 /reports 는 빈 화면이다 — 그
   * 경우 링크 대신 왜 아직 못 보는지 안내한다(missions/[missionId]/page.tsx 가
   * reports/page.tsx 와 같은 판정을 재사용해 계산). */
  hasComparisonReport: boolean;
}) {
  const [bundle, setBundle] = useState(initialBundle);
  const [items, setItems] = useState<UploadItem[]>([]);
  const [phase, setPhase] = useState<Phase>(() => {
    if (initialJob && !isTerminalJobStatus(initialJob.status)) return "job-running";
    if (initialJob?.status === "SUCCEEDED") return "job-done";
    if (initialJob?.status === "FAILED" || initialJob?.status === "CANCELLED") return "job-failed";
    if (initialBundle?.status === "SEALED") return "sealed";
    // 사진은 등록됐지만(OPEN) 아직 봉인 전 — 새로고침으로 이 상태에 진입했을 때
    // "idle"로 떨어지면 봉인 버튼이 사라져 막다른 길이 된다(reviewer 지적).
    if (initialBundle && initialBundle.mediaCount > 0) return "ready-to-seal";
    return "idle";
  });
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(initialJob?.jobId ?? null);
  const [jobStatus, setJobStatus] = useState<string | null>(initialJob?.status ?? null);
  const [jobDetail, setJobDetail] = useState<string | null>(initialJob?.detail ?? null);
  const [artifacts, setArtifacts] = useState<ProcessingArtifactSummary[]>([]);

  // jobId 가 생기거나 바뀔 때마다(마운트 시 복원 · handleIssue 발급 직후 둘 다)
  // 조회를 시작한다 — 진행 중이면 폴링을 이어가고, 이미 종료 상태라도 이 조회가
  // 있어야 artifacts 목록이 채워진다(서버 initialJob 은 jobId·status 만 넘긴다).
  // jobId 가 유일한 재시작 경로라는 것이 핵심이다(usePolling 모듈 docstring) —
  // handleIssue 가 직접 폴링을 불러 시작하면 그 시작은 cleanup 을 갖지 못해
  // unmount 시 setTimeout 체인이 정리되지 않는 누수였다(reviewer 지적).
  usePolling(
    jobId,
    async (id) => {
      const response = await fetch(`/api/processing-jobs/${encodeURIComponent(id)}`);
      if (!response.ok) return null;
      const body = await parseJsonSafe<
        Pick<ProcessingJobArtifactsView, "status" | "artifacts"> & { detail?: string | null }
      >(response);
      return body.status
        ? { status: body.status, artifacts: body.artifacts ?? [], detail: body.detail ?? null }
        : null;
    },
    (result) => isTerminalJobStatus(result.status),
    (result) => {
      setJobStatus(result.status);
      setJobDetail(result.detail);
      setArtifacts(result.artifacts);
      if (isTerminalJobStatus(result.status)) {
        setPhase(result.status === "SUCCEEDED" ? "job-done" : "job-failed");
      }
    },
  );

  async function refreshBundle() {
    try {
      const response = await fetch(`/api/missions/${encodeURIComponent(missionId)}/source-media`);
      if (!response.ok) return;
      const body = (await response.json()) as SourceMediaBundleView | null;
      setBundle(body);
      if (body?.status === "SEALED") setPhase("sealed");
      else if (body && body.mediaCount > 0) setPhase("ready-to-seal");
    } catch {
      // 조회 실패는 화면을 막지 않는다 — 다음 액션(봉인 버튼)에서 서버가 다시 판정한다.
    }
  }

  async function handleFiles(files: File[]) {
    setError(null);
    if (files.length === 0) return;
    const mediaIds = await assignUniqueMediaIds(files.map((f) => f.name));
    if (mediaIds === null) {
      // 같은 파일명이 완전히 같은 형태로 두 번 이상 선택됐다 — 해시 접미사는
      // 이름 자체의 함수라 이 경우는 갈라놓을 수 없다(값을 지어내지 않는다).
      setError("같은 이름의 파일이 두 번 이상 선택되었습니다 — 파일명을 확인하고 다시 선택하세요.");
      return;
    }
    const initial: UploadItem[] = files.map((file, i) => ({
      file,
      mediaId: mediaIds[i],
      status: "pending",
    }));
    setItems(initial);
    setPhase("uploading");

    let anyFailed = false;
    for (const batch of chunk(initial, BATCH_SIZE)) {
      const claims: SourceMediaFileClaim[] = [];
      for (const it of batch) {
        try {
          claims.push(await buildSourceMediaClaim(it.file, it.mediaId));
        } catch {
          anyFailed = true;
          const failedId = it.mediaId;
          setItems((prev) =>
            prev.map((p) =>
              p.mediaId === failedId ? { ...p, status: "error", message: "파일을 읽지 못했습니다" } : p,
            ),
          );
        }
      }
      if (claims.length === 0) continue;

      const claimIds = new Set(claims.map((c) => c.mediaId));
      setItems((prev) => prev.map((p) => (claimIds.has(p.mediaId) ? { ...p, status: "registering" } : p)));

      let registerResponse: Response;
      try {
        registerResponse = await fetch(`/api/missions/${encodeURIComponent(missionId)}/source-media`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ files: claims }),
        });
      } catch {
        anyFailed = true;
        setItems((prev) =>
          prev.map((p) => (claimIds.has(p.mediaId) ? { ...p, status: "error", message: "네트워크 오류" } : p)),
        );
        continue;
      }
      if (!registerResponse.ok) {
        const body = await parseJsonSafe<{ code?: string; message?: string }>(registerResponse);
        anyFailed = true;
        const message = readableError(body.code, body.message ?? "등록 실패");
        setItems((prev) =>
          prev.map((p) => (claimIds.has(p.mediaId) ? { ...p, status: "error", message } : p)),
        );
        continue;
      }
      const registerBody = (await registerResponse.json()) as SourceMediaBatchResponse;
      const { ready, failed } = summarizeUploadBatch(registerBody.results);
      if (failed.length > 0) anyFailed = true;
      setItems((prev) =>
        prev.map((p) => {
          const f = failed.find((x) => x.mediaId === p.mediaId);
          if (f) return { ...p, status: "error", message: readableError(f.verdict, f.detail ?? f.verdict) };
          return p;
        }),
      );

      // 바이트는 대시보드 서버를 거치지 않는다 — 브라우저가 스토리지로 직접 PUT.
      await Promise.all(
        ready.map(async ({ mediaId, uploadUrl }) => {
          const it = batch.find((b) => b.mediaId === mediaId);
          if (!it) return;
          setItems((prev) => prev.map((p) => (p.mediaId === mediaId ? { ...p, status: "uploading" } : p)));
          try {
            const put = await fetch(uploadUrl, {
              method: "PUT",
              headers: { "Content-Type": it.file.type || "application/octet-stream" },
              body: it.file,
            });
            if (!put.ok) throw new Error(String(put.status));
            setItems((prev) => prev.map((p) => (p.mediaId === mediaId ? { ...p, status: "done" } : p)));
          } catch {
            anyFailed = true;
            setItems((prev) =>
              prev.map((p) =>
                p.mediaId === mediaId ? { ...p, status: "error", message: "스토리지 업로드 실패" } : p,
              ),
            );
          }
        }),
      );
    }

    await refreshBundle();
    setPhase((current) => (current === "uploading" ? (anyFailed ? "uploading" : "ready-to-seal") : current));
    if (anyFailed) setError("일부 파일 처리에 실패했습니다 — 아래 목록에서 실패 항목을 확인하세요.");
  }

  async function handleSeal() {
    setPhase("sealing");
    setError(null);
    try {
      const response = await fetch(`/api/missions/${encodeURIComponent(missionId)}/source-media/seal`, {
        method: "POST",
      });
      const body = await parseJsonSafe<SourceMediaSealResponse>(response);
      if (!response.ok || !body.bundle) {
        setError(readableApiError(body, "봉인에 실패했습니다"));
        setPhase("ready-to-seal");
        return;
      }
      setBundle(body.bundle);
      setPhase("sealed");
    } catch {
      setError("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
      setPhase("ready-to-seal");
    }
  }

  async function handleIssue() {
    setPhase("issuing");
    setError(null);
    try {
      const response = await fetch(`/api/missions/${encodeURIComponent(missionId)}/processing-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(RECONSTRUCTION_SPEC),
      });
      const body = await parseJsonSafe<ProcessingJobMutationResponse>(response);
      if (!response.ok || !body.job) {
        setError(readableApiError(body, "재구성 작업 발행에 실패했습니다"));
        setPhase("sealed");
        return;
      }
      setJobStatus(body.job.status);
      setJobDetail(body.job.detail);
      setArtifacts([]);
      setPhase(isTerminalJobStatus(body.job.status) ? (body.job.status === "SUCCEEDED" ? "job-done" : "job-failed") : "job-running");
      // jobId 를 마지막에 설정한다 — 이 값이 바뀌는 것 자체가 폴링 effect 를
      // 트리거한다(중복 호출 없이 cleanup 을 항상 보장하는 단일 경로).
      setJobId(body.job.jobId);
    } catch {
      setError("요청을 처리하지 못했습니다. 네트워크 상태를 확인하세요.");
      setPhase("sealed");
    }
  }

  const busy = phase === "uploading" || phase === "sealing" || phase === "issuing";
  const completedItemCount = items.filter((item) => item.status === "done").length;
  const failedItems = items.filter((item) => item.status === "error");

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
          사진 업로드 · 재구성
        </h3>
        {bundle && (
          <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
            등록된 사진 {bundle.mediaCount}장 · {bundle.status === "SEALED" ? "봉인됨" : "봉인 전"}
          </span>
        )}
      </div>

      <p className="text-[12.5px] break-keep text-ink-muted">
        <strong className="font-bold text-ink-2">KSI 표준 처리 v1</strong> · DSM·DTM과
        중간 품질 점군을 같은 고정 프로필로 처리합니다. 처리값은 이 화면에서 바꿀 수
        없으며, 시계열·물량 비교의 일관성을 위해 Core 원장에 함께 고정됩니다.
      </p>

      {error && (
        <p className="rounded-md bg-crit-bg px-3 py-2 text-[12.5px] font-semibold break-keep text-crit-ink">
          {error}
        </p>
      )}

      {!canIssue && !bundle && (
        <p className="text-[12.5px] break-keep text-ink-muted">
          사진을 올리려면 임무 발급 권한(MISSIONS_ISSUE)이 필요합니다.
        </p>
      )}

      {canIssue && phase !== "sealed" && phase !== "job-running" && phase !== "job-done" && (
        <div className="flex flex-col gap-2">
          <label className="tap-target flex w-fit cursor-pointer items-center rounded-md border border-line-strong px-3 text-[13px] font-semibold break-keep hover:bg-sunk">
            {phase === "uploading" ? "올리는 중…" : "사진 선택"}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              disabled={busy}
              className="sr-only"
              onChange={(event) => {
                // input.files 는 라이브 뷰다 — Array.from 으로 먼저 떼어내지 않고
                // value 를 비우면 이미 잡아둔 참조까지 함께 비어버린다(단일 파일만
                // 다루는 EvidencePanel 은 File 객체를 바로 꺼내 써서 이 문제가 없다).
                const files = Array.from(event.target.files ?? []);
                event.target.value = "";
                if (files.length > 0) void handleFiles(files);
              }}
            />
          </label>

          {items.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-[11.5px] break-keep text-ink-muted">
                이번 선택 {items.length}개 · 완료 {completedItemCount}개 · 실패 {failedItems.length}개
              </p>
              <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto rounded-md border border-line bg-sunk p-2">
                {items.map((it) => (
                  <li
                    key={it.mediaId}
                    className="flex items-center justify-between gap-2 text-[11.5px] break-keep"
                  >
                    <span className="num truncate text-ink-2">{it.mediaId}</span>
                    <span
                      className={
                        it.status === "error"
                          ? "text-crit-ink"
                          : it.status === "done"
                            ? "text-safe-ink"
                            : "text-ink-muted"
                      }
                    >
                      {it.message ?? FILE_STATUS_LABEL[it.status]}
                    </span>
                  </li>
                ))}
              </ul>
              {failedItems.length > 0 && (
                <button
                  type="button"
                  className="btn w-fit"
                  disabled={busy}
                  onClick={() => void handleFiles(failedItems.map((item) => item.file))}
                >
                  실패 파일 다시 시도 ({failedItems.length})
                </button>
              )}
            </div>
          )}

          {(phase === "ready-to-seal" || phase === "sealing") && (
            <button
              type="button"
              onClick={() => void handleSeal()}
              disabled={busy}
              className="btn btn-primary w-fit"
            >
              {phase === "sealing" ? "봉인하는 중…" : "업로드 마치고 봉인하기"}
            </button>
          )}
        </div>
      )}

      {canIssue && (phase === "sealed" || phase === "issuing") && (
        <div className="flex flex-col gap-2">
          <p className="text-[12.5px] break-keep text-ink-muted">
            번들이 봉인되었습니다 — 재구성 작업을 발행하면 서버가 이 사진들로 3D 재구성을 시작합니다.
          </p>
          <button
            type="button"
            onClick={() => void handleIssue()}
            disabled={phase === "issuing"}
            className="btn btn-primary w-fit"
          >
            {phase === "issuing" ? "발행하는 중…" : "재구성 작업 발행"}
          </button>
        </div>
      )}

      {jobId && (phase === "job-running" || phase === "job-done" || phase === "job-failed") && (
        <div className="flex flex-col gap-2 border-t border-line pt-3">
          <div className="flex flex-wrap items-center gap-2">
            {jobStatus && (
              <StatusBadge
                label={PROCESSING_JOB_STATUS_LABEL[jobStatus]?.label ?? jobStatus}
                tone={PROCESSING_JOB_STATUS_LABEL[jobStatus]?.tone ?? "neutral"}
              />
            )}
            <span className="num text-[11.5px] break-token text-ink-muted">{jobId}</span>
          </div>

          {phase === "job-running" && (
            <p className="text-[12.5px] break-keep text-ink-muted">
              재구성이 진행 중입니다 — 사진 수·서버 부하에 따라 수 분~수십 분 걸릴 수 있습니다.
              이 화면을 열어두지 않아도 됩니다(다시 방문하면 진행 상태를 이어서 보여줍니다).
            </p>
          )}

          {phase === "job-done" && (
            <>
              <p className="text-[12.5px] break-keep text-safe-ink">
                재구성이 완료되었습니다 — 산출물 {artifacts.length}건 등록됨
                {artifacts.length > 0 && ` (${artifacts.map((a) => a.kind).join(", ")})`}.
              </p>
              {hasComparisonReport ? (
                <Link
                  href={`/reports?missionId=${encodeURIComponent(missionId)}`}
                  className="btn btn-primary w-fit"
                >
                  리포트 확인
                </Link>
              ) : (
                <p className="text-[12.5px] break-keep text-ink-muted">
                  변화·물량 비교 리포트는 아직 없습니다 — 같은 현장을 두 번(이번
                  재구성 + 비교할 다른 시점의 재구성) 완주한 뒤, 아래 <strong>두 시점
                  비교</strong>에서 두 결과를 골라 제출하면 만들어집니다.
                </p>
              )}
            </>
          )}

          {phase === "job-failed" && (
            <div className="flex flex-col gap-2">
              <p className="text-[12.5px] break-keep text-crit-ink">
                재구성 작업이 {jobStatus === "CANCELLED" ? "취소되었습니다" : "실패했습니다"}.
                {jobDetail ? ` ${jobDetail}` : " 서버 상세 사유를 확인할 수 없습니다."}
              </p>
              {canReissueProcessingJob(jobStatus, canIssue) && (
                <button
                  type="button"
                  onClick={() => void handleIssue()}
                  className="btn btn-primary w-fit"
                >
                  같은 봉인 사진으로 재구성 다시 시도
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
